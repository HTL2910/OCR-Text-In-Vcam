"""Generate a crisp multi-resolution Windows .ico file for OCR Text In Vcam."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def generate_icon(output_path: Path) -> None:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded dark-slate badge with subtle cyan border
    draw.rounded_rectangle(
        (10, 10, size - 10, size - 10),
        radius=48,
        fill=(15, 23, 42, 255),
        outline=(56, 189, 248, 255),
        width=8,
    )

    # Corner viewfinder brackets (camera / ROI capture motif)
    c = (34, 211, 238, 255)
    m = 42
    arm = 38
    w = 10
    # Top-left
    draw.line([(m, m + arm), (m, m), (m + arm, m)], fill=c, width=w, joint="curve")
    # Top-right
    draw.line([(size - m - arm, m), (size - m, m), (size - m, m + arm)], fill=c, width=w, joint="curve")
    # Bottom-left
    draw.line([(m, size - m - arm), (m, size - m), (m + arm, size - m)], fill=c, width=w, joint="curve")
    # Bottom-right
    draw.line(
        [(size - m - arm, size - m), (size - m, size - m), (size - m, size - m - arm)],
        fill=c,
        width=w,
        joint="curve",
    )

    # OCR text label in center
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 64)
    except Exception:
        font = ImageFont.load_default()
    text = "OCR"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1] - 12
    draw.text((tx, ty), text, fill=(248, 250, 252, 255), font=font)

    # Glowing horizontal scan beam under OCR
    draw.rounded_rectangle((56, 166, size - 56, 178), radius=6, fill=(14, 165, 233, 255))
    draw.rounded_rectangle((74, 190, size - 74, 198), radius=4, fill=(148, 163, 184, 200))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(
        output_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    out = root / "assets" / "app.ico"
    generate_icon(out)
    print(f"Generated icon: {out}")
