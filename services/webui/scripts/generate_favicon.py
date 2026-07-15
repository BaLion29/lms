"""Generate favicon.ico from the firn-mark motif using Pillow.

One-off script — run via ``uv run --with pillow python scripts/generate_favicon.py``
from the ``services/webui/`` directory. Pillow is NOT a project dependency.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

SIZES: list[tuple[int, int]] = [(48, 48), (32, 32), (16, 16)]
BG = (28, 32, 36)  # #1c2024
FG = (45, 212, 191)  # #2dd4bf


def _coord(x: float, y: float, w: int, h: int) -> tuple[int, int]:
    """Map 24×24 design-space coords to target size."""
    return int(x * w / 24), int(y * h / 24)


def main() -> None:
    frames: list[Image.Image] = []
    for w, h in SIZES:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Rounded-square background
        radius = max(1, w // 5)
        draw.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=BG)

        lw = max(1, w // 16)

        # Mountain triangle: (3,20) -> (12,4) -> (21,20)
        pts = [
            _coord(3, 20, w, h),
            _coord(12, 4, w, h),
            _coord(21, 20, w, h),
        ]
        draw.line(pts + [pts[0]], fill=FG, width=lw)

        # Firn line across upper third
        draw.line(
            [_coord(5.5, 11, w, h), _coord(18.5, 11, w, h)],
            fill=FG,
            width=lw,
        )

        frames.append(img)

    frames[0].save(
        "assets/favicon.ico",
        format="ICO",
        sizes=[(f.width, f.height) for f in frames],
        append_images=frames[1:],
    )
    print(
        f"assets/favicon.ico written with sizes: "
        f"{', '.join(f'{f.width}×{f.height}' for f in frames)}",
    )


if __name__ == "__main__":
    main()
