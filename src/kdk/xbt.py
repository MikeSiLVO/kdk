"""Kodi Textures.xbt bundles: pack a media folder into one, and unpack one back into image files."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import threading
from dataclasses import dataclass, field
from typing import BinaryIO, Callable

from kdk.libs.utils.files import is_inside

INSTALL_HINT = 'pip install "kdk[textures]"'
_ENTRY = struct.Struct("<II")
_FRAME = struct.Struct("<IIIQQIQ")
_OPAQUE = 0x10000
_LEGACY_BGRA = 0x10
_LEGACY_DXT = {0x1: 1, 0x2: 2, 0x4: 3}
_RAW_MODES = {0x1000: ("L", "L"), 0x1100: ("LA", "LA"), 0x1600: ("RGBA", "RGBA"), 0x1700: ("RGBA", "BGRA")}
_BCN = {0x4000: 1, 0x4100: 1, 0x4200: 2, 0x4300: 3}
_ALPHA_ONLY = 0x300000
_INTENSITY = 0x500000
_SAVE_AS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".gif": "GIF"}
_NAME_BYTES = 256
_MEDIA_REF = re.compile(r"[^<>\"'\s=]+\.(?:png|jpe?g|gif)\b", re.IGNORECASE)


@dataclass
class Frame:
    """One frame of a texture: its size, pixel format, where its data sits and how long it shows."""

    width: int
    height: int
    format: int
    packed_size: int
    unpacked_size: int
    duration: int
    offset: int


@dataclass
class Texture:
    """One packed image: its path inside the bundle and its frames, more than one when animated."""

    path: str
    frames: list[Frame] = field(default_factory=list)


@dataclass
class UnpackResult:
    """What an unpack wrote, kept as it was, could not read, and named in the skin's own case."""

    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    recased: int = 0
    cancelled: bool = False


@dataclass
class PackResult:
    """What a pack stored, what it could not read, and how many images reuse another's data."""

    packed: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    duplicates: int = 0
    cancelled: bool = False


def missing_libraries() -> str:
    """Install command for Pillow and lzallright when either is missing, else empty."""
    try:
        import lzallright  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        return INSTALL_HINT
    return ""


def read_index(path: str) -> list[Texture]:
    """Read the bundle's index of textures; ValueError when the file is no readable bundle."""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"XBTF":
                raise ValueError(f"{os.path.basename(path)} is not a Kodi texture bundle")
            if f.read(1) < b"2":
                raise ValueError(f"{os.path.basename(path)} is from a bundle version kdk cannot read")
            (count,) = struct.unpack("<I", f.read(4))
            textures = []
            for _ in range(count):
                name = f.read(256).split(b"\0", 1)[0].decode("utf-8", "replace").replace("\\", "/")
                _loop, frames = _ENTRY.unpack(f.read(_ENTRY.size))
                textures.append(Texture(name, [Frame(*_FRAME.unpack(f.read(_FRAME.size))) for _ in range(frames)]))
            return textures
    except struct.error:
        raise ValueError(f"{os.path.basename(path)} ends partway through its index") from None


def frame_image(handle: BinaryIO, frame: Frame):
    """Pixels of one frame as a Pillow image; ValueError for a pixel format kdk cannot read."""
    from lzallright import LZOCompressor
    from PIL import Image

    handle.seek(frame.offset)
    data = handle.read(frame.packed_size)
    if frame.packed_size != frame.unpacked_size:
        data = LZOCompressor().decompress(data, output_size_hint=frame.unpacked_size)
    size = (frame.width, frame.height)
    kind = frame.format & 0xFF00
    if frame.format & 0xF000:
        if kind in _RAW_MODES:
            mode, raw = _RAW_MODES[kind]
            image = Image.frombuffer(mode, size, data, "raw", raw, 0, 1)
        elif kind in _BCN:
            image = Image.frombytes("RGBA", size, data, "bcn", _BCN[kind])
        else:
            raise ValueError(f"pixel format {kind:#06x}")
        swizzle = frame.format & 0xF00000
        if image.mode == "L" and swizzle == _ALPHA_ONLY:
            image = Image.merge("RGBA", (*[Image.new("L", size, 255)] * 3, image.getchannel(0)))
        elif image.mode == "L" and swizzle == _INTENSITY:
            image = Image.merge("LA", (image, image))
    elif frame.format & 0xFFFF == _LEGACY_BGRA:
        image = Image.frombuffer("RGBA", size, data, "raw", "BGRA", 0, 1)
    elif frame.format & 0xFFFF in _LEGACY_DXT:
        image = Image.frombytes("RGBA", size, data, "bcn", _LEGACY_DXT[frame.format & 0xFFFF])
    else:
        raise ValueError(f"pixel format {frame.format & 0xFFFF:#06x}")
    if frame.format & _OPAQUE and image.mode in ("RGBA", "LA"):
        image = image.convert("RGB" if image.mode == "RGBA" else "L")
    return image


def skin_of(bundle: str) -> str:
    """Skin folder two levels above the bundle, empty when that folder holds no addon.xml."""
    skin = os.path.dirname(os.path.dirname(os.path.abspath(bundle)))
    return skin if os.path.isfile(os.path.join(skin, "addon.xml")) else ""


def media_names(skin: str) -> dict[str, str]:
    """Media paths as the skin's XML writes them, by lowercased form; the first spelling wins."""
    names: dict[str, str] = {}
    for root, dirs, files in os.walk(skin):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "media"]
        for name in files:
            if not name.lower().endswith(".xml"):
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            for ref in _MEDIA_REF.findall(text):
                ref = re.sub(r"^special://skin/media/", "", ref, flags=re.IGNORECASE).replace("\\", "/")
                names.setdefault(ref.lower(), ref)
    return names


def unpack(bundle: str, folder: str, names: dict[str, str] | None = None, overwrite: bool = False,
           progress: Callable[[int, int, str], None] | None = None,
           cancel: threading.Event | None = None) -> UnpackResult:
    """Unpack each texture into the folder in its source format; existing files stay unless told."""
    textures = read_index(bundle)
    result = UnpackResult()
    with open(bundle, "rb") as handle:
        for n, texture in enumerate(textures, 1):
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                break
            if progress:
                progress(n, len(textures), texture.path)
            rel = (names or {}).get(texture.path.lower(), texture.path)
            target = os.path.join(folder, rel)
            if not texture.frames or not is_inside(target, folder):
                result.unreadable.append(texture.path)
                continue
            if os.path.exists(target) and not overwrite:
                result.kept.append(rel)
                continue
            try:
                images = [frame_image(handle, frame) for frame in texture.frames]
            except (ValueError, OSError):
                result.unreadable.append(texture.path)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _save(images, texture, target)
            result.written.append(rel)
            result.recased += rel != texture.path
    return result


def media_files(folder: str, bundle: str = "") -> list[str]:
    """PNG, JPG and GIF files under the folder as sorted relative paths; hidden folders left out."""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in files:
            path = os.path.join(root, name)
            if os.path.splitext(name)[1].lower() in _SAVE_AS and os.path.abspath(path) != os.path.abspath(bundle):
                found.append(os.path.relpath(path, folder).replace(os.sep, "/"))
    return sorted(found)


def pack(folder: str, bundle: str, progress: Callable[[int, int, str], None] | None = None,
         cancel: threading.Event | None = None) -> PackResult:
    """Pack the folder's images into a version 2 bundle, the format Omega and Piers both read."""
    from lzallright import LZOCompressor
    from PIL import Image, ImageSequence

    lzo = LZOCompressor()
    files = media_files(folder, bundle)
    result = PackResult()
    entries: list[tuple[str, list[tuple]]] = []
    stored: dict[bytes, list[tuple]] = {}
    names: set[str] = set()
    data_path = f"{bundle}.data.part"
    with open(data_path, "wb") as data:
        for n, rel in enumerate(files, 1):
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                break
            if progress:
                progress(n, len(files), rel)
            name = rel.lower()
            if name in names or len(name.encode("utf-8")) >= _NAME_BYTES:
                result.unreadable.append(rel)
                continue
            try:
                with Image.open(os.path.join(folder, rel)) as image:
                    frames = [(frame.convert("RGBA"), int(frame.info.get("duration") or 0))
                              for frame in ImageSequence.Iterator(image)]
            except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
                result.unreadable.append(rel)
                continue
            raws = [image.tobytes("raw", "BGRA") for image, _duration in frames]
            digest = hashlib.sha1(b"".join(struct.pack("<II", *image.size) + raw
                                           for (image, _d), raw in zip(frames, raws))).digest()
            if digest in stored:
                result.duplicates += 1
            else:
                stored[digest] = [_store(data, lzo, image, duration, raw) for (image, duration), raw in zip(frames, raws)]
            names.add(name)
            entries.append((name, stored[digest]))
            result.packed.append(rel)
    if result.cancelled:
        os.remove(data_path)
        return result
    _write_bundle(bundle, entries, data_path)
    return result


def _store(data: BinaryIO, lzo, image, duration: int, raw: bytes) -> tuple:
    """Store one frame's pixels in the data file, LZO-packed when smaller; its index record."""
    opaque = image.getchannel("A").getextrema() == (255, 255)
    packed = lzo.compress(raw)
    body = packed if len(packed) < len(raw) else raw
    record = (image.width, image.height, _LEGACY_BGRA | (_OPAQUE if opaque else 0), len(body), len(raw),
              duration, data.tell())
    data.write(body)
    return record


def _write_bundle(bundle: str, entries: list[tuple[str, list[tuple]]], data_path: str):
    """Write header and index with absolute frame offsets, then the data, replacing the bundle."""
    start = 9 + sum(_NAME_BYTES + _ENTRY.size + _FRAME.size * len(records) for _name, records in entries)
    part = f"{bundle}.part"
    with open(part, "wb") as out:
        out.write(b"XBTF2" + struct.pack("<I", len(entries)))
        for name, records in entries:
            out.write(name.encode("utf-8").ljust(_NAME_BYTES, b"\0") + _ENTRY.pack(0, len(records)))
            for width, height, fmt, packed, unpacked, duration, offset in records:
                out.write(_FRAME.pack(width, height, fmt, packed, unpacked, duration, start + offset))
        with open(data_path, "rb") as data:
            shutil.copyfileobj(data, out)
    os.remove(data_path)
    os.replace(part, bundle)


def _save(images: list, texture: Texture, target: str):
    """Save the image in the extension's format, PNG if unknown; only a GIF keeps every frame."""
    kind = _SAVE_AS.get(os.path.splitext(target)[1].lower(), "PNG")
    first = images[0]
    if kind == "JPEG":
        first.convert("RGB").save(target, "JPEG", quality=95)
    elif kind == "GIF" and len(images) > 1:
        first.save(target, "GIF", save_all=True, append_images=images[1:], loop=0, disposal=2,
                   duration=[max(frame.duration, 20) for frame in texture.frames])
    else:
        first.save(target, kind)
