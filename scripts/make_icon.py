"""Render `assets/kdk-icon.svg` into a multi-resolution `src/kdk/data/icon.ico`.

Run locally whenever the SVG changes; commit the resulting .ico. End users and
CI never need to run this - they pick up the committed file.

Uses PySide6's QSvgRenderer (already a runtime dep on the dev machine) plus
Pillow. Install both with `pip install -e ".[build]"`.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = REPO_ROOT / "assets" / "kdk-icon.svg"
OUT_PATH = REPO_ROOT / "src" / "kdk" / "data" / "icon.ico"

# Sizes Windows/macOS/Linux taskbars and Explorer ask for at various DPIs.
SIZES = [16, 24, 32, 48, 64, 128, 256]


def _render_png(svg_bytes: bytes, size: int) -> bytes:
    """Rasterize `svg_bytes` to a `sizexsize` PNG via Qt."""
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    # QImage needs a QApplication (or at least a QGuiApplication) live.
    QApplication.instance() or QApplication(sys.argv)

    renderer = QSvgRenderer(QByteArray(svg_bytes))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()

    buf = QByteArray()
    from PySide6.QtCore import QBuffer
    qbuf = QBuffer(buf)
    qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(qbuf, "PNG")
    return bytes(buf)


def main() -> int:
    if not SVG_PATH.is_file():
        print(f"Missing source SVG: {SVG_PATH}", file=sys.stderr)
        return 1

    try:
        from PIL import Image
    except ImportError:
        print(
            'Pillow not installed. Run: pip install -e ".[build]"',
            file=sys.stderr,
        )
        return 1

    svg_bytes = SVG_PATH.read_bytes()
    print(f"Rendering {SVG_PATH.name} at sizes: {SIZES}")

    # Render each size (Pillow's ICO save can downsample one image, but rendering
    # at native size keeps the smallest faces sharp).
    images = []
    for size in SIZES:
        png = _render_png(svg_bytes, size)
        images.append(Image.open(io.BytesIO(png)).convert("RGBA"))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Pillow packs all images into one .ico, picking the right one per request size.
    images[-1].save(OUT_PATH, format="ICO",
                    sizes=[(s, s) for s in SIZES],
                    append_images=images[:-1])
    print(f"Wrote {OUT_PATH}  ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
