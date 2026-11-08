"""Checks of the artwork: declared images, their format, size, file size and transparency."""

from __future__ import annotations

import os
import re

from ..libs.utils.images import get_image_info, has_transparent_pixels
from ..libs.validation.repo import ARTWORK
from .rules import finding
from .submission import Submission

# add-on kinds the Kodi repo's checker asks no fanart of, by a part of the add-on's folder name
NO_FANART = (".module.", "metadata.", "context.", ".language.")
FALLBACK = {"icon": "icon.png", "fanart": "fanart.jpg"}
IMAGE_NAME = re.compile(r"(?!fanart\.jpg|icon\.png).*\.(png|jpg|jpeg|gif)$")


def check(sub: Submission) -> list[dict]:
    """Issue rows for <assets> images, undeclared or unreadable ones and unlisted screenshots."""
    if sub.root is None or sub.broken:
        return []
    rows, listed, unreadable = [], set(), set()
    for kind, spec in ARTWORK.items():
        nodes = sub.root.findall(f"extension/assets/{kind}")
        for node in nodes:
            image = (node.text or "").strip().replace("\\", "/")
            if not image:
                rows.append(finding("art.empty-tag", sub.xml_path, node.sourceline, kind,
                                    f"<{kind}> in <assets> is empty; remove it or name an image"))
                continue
            listed.add(os.path.normpath(image).replace(os.sep, "/"))
            if not os.path.isfile(sub.abs(image)):
                rows.append(finding("art.missing", sub.xml_path, node.sourceline, kind,
                                    f"{kind.capitalize()} {image} does not exist"))
                continue
            rows += _image_rows(sub, kind, image, spec, unreadable)
        fallback = FALLBACK.get(kind)
        if nodes or not fallback or (kind == "fanart" and any(part in sub.folder for part in NO_FANART)):
            continue
        if fallback in sub.files:
            rows.append(finding("art.undeclared", sub.abs(fallback), 0, kind,
                                f"{fallback} is not declared in addon.xml; list it as <{kind}> in <assets>"))
            rows += _image_rows(sub, kind, fallback, spec, unreadable)
        else:
            rows.append(finding(f"art.no-{kind}", sub.xml_path, sub.root.sourceline, kind,
                                f"The add-on has no {kind}; add one and list it in <assets>"))
    for rel in sorted(sub.files):
        name = rel.rpartition("/")[2]
        if rel not in unreadable and IMAGE_NAME.match(name) and "Type" not in dict(get_image_info(sub.abs(rel))):
            rows.append(finding("art.unreadable", sub.abs(rel), 0, rel,
                                f"{rel} cannot be read as an image; it may be damaged or another format"))
        if "screenshot" in rel.lower() and name.lower().endswith((".png", ".jpg", ".jpeg", ".gif")) and \
                rel not in listed:
            rows.append(finding("art.screenshot-unlisted", sub.abs(rel), 0, rel,
                                f"{rel} looks like a screenshot but <assets> does not list it"))
    return rows


def _image_rows(sub: Submission, kind: str, image: str, spec, unreadable: set[str]) -> list[dict]:
    """One image against its kind's specs; an unreadable one goes in the set with that row alone."""
    extensions, sizes, max_kb, transparent = spec
    path = sub.abs(image)
    info = dict(get_image_info(path))
    if "Type" not in info:
        unreadable.add(image)
        return [finding("art.unreadable", path, 0, image,
                        f"{kind.capitalize()} {image} cannot be read as an image; it may be damaged or another "
                        f"format")]
    rows = []
    ext = os.path.splitext(image)[1]
    if ext not in extensions:
        rows.append(finding("art.type", path, 0, kind,
                            f"{kind.capitalize()} must be {' or '.join(extensions)}, not "
                            f"{ext or 'without an ending'}"))
    if transparent is not None:
        has_alpha = has_transparent_pixels(path) is True
        if has_alpha and not transparent:
            rows.append(finding("art.transparency", path, 0, kind,
                                f"{kind.capitalize()} has transparent pixels; the Kodi repo wants it solid"))
        elif transparent and not has_alpha:
            rows.append(finding("art.transparency", path, 0, kind,
                                f"{kind.capitalize()} has no transparent pixels; the Kodi repo wants a transparent "
                                f"background"))
    dims = info.get("Dimensions", "")
    if dims and tuple(int(v) for v in dims.split("x")) not in sizes:
        allowed = " or ".join(f"{w}x{h}" for w, h in sizes)
        rows.append(finding("art.size", path, 0, kind,
                            f"{kind.capitalize()} is {dims}; the Kodi repo accepts {allowed}"))
    if max_kb and os.path.getsize(path) > max_kb * 1024:
        rows.append(finding("art.file-size", path, 0, kind,
                            f"{kind.capitalize()} is {os.path.getsize(path) // 1024}KB, over the {max_kb}KB limit"))
    return rows
