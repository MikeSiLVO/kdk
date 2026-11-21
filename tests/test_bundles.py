"""Packing images into Kodi texture bundles and unpacking them again (kdk-only; textures extra)."""

import random
import struct
import threading

import pytest

pytest.importorskip("PIL")
pytest.importorskip("lzallright")

from lzallright import LZOCompressor  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

from kdk import xbt  # noqa: E402

BGRA = 0x10
OPAQUE = 0x10000


def _noise(mode, size, seed):
    """Image of random pixels in the mode, the same for the same seed."""
    rng = random.Random(seed)
    bands = len(Image.new(mode, (1, 1)).getbands())
    return Image.frombytes(mode, size, bytes(rng.randrange(256) for _ in range(size[0] * size[1] * bands)))


def _media(folder):
    """Folder of RGBA, RGB, gray and palette PNGs, a JPG, a GIF, a duplicate and broken files."""
    (folder / "Icons" / "Sub").mkdir(parents=True)
    (folder / ".hidden").mkdir()
    _noise("RGBA", (37, 21), 1).save(folder / "Icons" / "Clear.png")
    _noise("RGB", (16, 16), 2).save(folder / "Icons" / "solid.png")
    _noise("L", (9, 30), 3).save(folder / "Icons" / "Sub" / "gray.png")
    palette = _noise("P", (12, 12), 4)
    palette.info["transparency"] = 0
    palette.save(folder / "palette.png")
    _noise("RGBA", (37, 21), 1).save(folder / "copy.png")
    _noise("RGB", (64, 40), 5).save(folder / "back.jpg", quality=95)
    frames = [_noise("RGB", (10, 10), seed).quantize(16) for seed in (6, 7, 8)]
    frames[0].save(folder / "spin.gif", save_all=True, append_images=frames[1:], duration=[50, 70, 90], loop=0)
    good = (folder / "Icons" / "Clear.png").read_bytes()
    (folder / "cut.png").write_bytes(good[: len(good) // 2])
    (folder / "empty.png").write_bytes(b"")
    (folder / "text.png").write_text("not an image")
    (folder / "notes.txt").write_text("not packed")
    _noise("RGB", (4, 4), 9).save(folder / ".hidden" / "skip.png")


def test_pack_then_unpack_gives_back_every_pixel(tmp_path):
    """Every readable image survives the round trip; broken files are listed and skipped."""
    media = tmp_path / "media"
    _media(media)
    bundle = str(media / "Textures.xbt")
    packed = xbt.pack(str(media), bundle)
    assert sorted(packed.unreadable) == ["cut.png", "empty.png", "text.png"]
    assert packed.duplicates == 1
    assert sorted(t.path for t in xbt.read_index(bundle)) == sorted(p.lower() for p in packed.packed)

    out = tmp_path / "out"
    result = xbt.unpack(bundle, str(out))
    assert not result.unreadable
    for rel in packed.packed:
        source = Image.open(media / rel).convert("RGBA")
        back = Image.open(out / rel.lower()).convert("RGBA")
        assert source.size == back.size, rel
        if rel.endswith(".jpg"):
            assert max(abs(a - b) for a, b in zip(source.tobytes(), back.tobytes())) < 40, rel
        else:
            assert not ImageChops.difference(source, back).getbbox(), rel
    assert getattr(Image.open(out / "spin.gif"), "n_frames", 1) == 3
    assert not list(tmp_path.rglob("*.part"))


def test_pack_marks_opaque_images_and_keeps_frame_delays(tmp_path):
    """Images with no transparent pixel are flagged opaque; GIF frames keep their own delays."""
    media = tmp_path / "media"
    _media(media)
    bundle = str(tmp_path / "Textures.xbt")
    xbt.pack(str(media), bundle)
    index = {t.path: t for t in xbt.read_index(bundle)}
    assert index["icons/solid.png"].frames[0].format == BGRA | OPAQUE
    assert index["icons/clear.png"].frames[0].format == BGRA
    assert [f.duration for f in index["spin.gif"].frames] == [50, 70, 90]


def test_cancelled_pack_leaves_no_bundle_behind(tmp_path):
    """Cancelling stops the pack and leaves neither the bundle nor its working files."""
    media = tmp_path / "media"
    _media(media)
    cancel = threading.Event()
    result = xbt.pack(str(media), str(tmp_path / "Textures.xbt"), progress=lambda *_a: cancel.set(), cancel=cancel)
    assert result.cancelled
    assert not list(tmp_path.glob("Textures.xbt*"))


def _frame(image, fmt=BGRA, pack=True):
    """Frame for a hand-made bundle: pixels in the format's byte order, with a flag to LZO-pack."""
    raw = image.tobytes("raw", "RGBA" if fmt & 0xFF00 == 0x1600 else "BGRA")
    return raw, image.width, image.height, fmt, pack


def _bundle(path, entries):
    """Hand-made version 2 bundle of named frame lists, for cases the packer never writes."""
    header = b"XBTF2" + struct.pack("<I", len(entries))
    offset = len(header) + sum(264 + 40 * len(frames) for _name, frames in entries)
    index, blobs = b"", []
    for name, frames in entries:
        index += name.encode().ljust(256, b"\0") + struct.pack("<II", 0, len(frames))
        for raw, width, height, fmt, pack in frames:
            body = LZOCompressor().compress(raw) if pack else raw
            index += struct.pack("<IIIQQIQ", width, height, fmt, len(body), len(raw), 0, offset)
            blobs.append(body)
            offset += len(body)
    path.write_bytes(header + index + b"".join(blobs))
    return str(path)


def test_unpack_reads_newer_pixel_formats_and_keeps_existing_files(tmp_path):
    """An RGBA8 frame from a newer packer reads back; an existing file stays unless overwritten."""
    image = Image.new("RGBA", (3, 2), (1, 2, 3, 4))
    bundle = _bundle(tmp_path / "Textures.xbt", [("kd.png", [_frame(image, 0x1600)])])
    out = tmp_path / "out"
    assert xbt.unpack(bundle, str(out)).written == ["kd.png"]
    assert Image.open(out / "kd.png").getpixel((2, 1)) == (1, 2, 3, 4)
    assert xbt.unpack(bundle, str(out)).kept == ["kd.png"]
    assert xbt.unpack(bundle, str(out), overwrite=True).written == ["kd.png"]


def test_unpack_takes_the_skins_case_and_never_leaves_the_folder(tmp_path):
    """A name the skin's XML writes in mixed case gets that case; a name climbing out is refused."""
    skin = tmp_path / "skin.test"
    (skin / "media").mkdir(parents=True)
    (skin / "1080i").mkdir()
    (skin / "addon.xml").write_text("<addon/>")
    (skin / "1080i" / "Home.xml").write_text(
        "<window><texture>special://skin/media/Buttons/Focus.png</texture></window>")
    pixel = _frame(Image.new("RGBA", (1, 1), (1, 1, 1, 255)))
    bundle = _bundle(skin / "media" / "Textures.xbt", [("buttons/focus.png", [pixel]), ("../escape.png", [pixel])])
    assert xbt.skin_of(bundle) == str(skin)
    result = xbt.unpack(bundle, str(tmp_path / "out"), names=xbt.media_names(str(skin)))
    assert result.written == ["Buttons/Focus.png"] and result.recased == 1
    assert result.unreadable == ["../escape.png"]
    assert not (tmp_path / "escape.png").exists()


def test_a_file_that_is_no_bundle_is_refused(tmp_path):
    """A file without the bundle header, or cut short in its index, raises ValueError."""
    (tmp_path / "not.xbt").write_bytes(b"PNG....")
    with pytest.raises(ValueError):
        xbt.read_index(str(tmp_path / "not.xbt"))
    (tmp_path / "short.xbt").write_bytes(b"XBTF2" + struct.pack("<I", 3))
    with pytest.raises(ValueError):
        xbt.read_index(str(tmp_path / "short.xbt"))
