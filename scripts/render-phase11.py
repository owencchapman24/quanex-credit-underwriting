"""Render the approved Phase 10 PDFs into a disposable Phase 11 QA directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw


def render_pdf(source: Path, output: Path) -> dict[str, object]:
    document = pdfium.PdfDocument(source)
    page_paths: list[Path] = []
    blank_pages: list[int] = []
    for index in range(len(document)):
        image = document[index].render(scale=1.5).to_pil().convert("RGB")
        path = output / f"{source.stem}-page-{index + 1:02d}.png"
        image.save(path, format="PNG", optimize=False)
        page_paths.append(path)
        if image.convert("L").getextrema()[0] >= 250:
            blank_pages.append(index + 1)

    thumb_width = 480
    thumbs: list[Image.Image] = []
    for path in page_paths:
        image = Image.open(path).convert("RGB")
        height = round(image.height * thumb_width / image.width)
        thumbs.append(image.resize((thumb_width, height)))
    columns = 3 if len(thumbs) > 1 else 1
    rows = (len(thumbs) + columns - 1) // columns
    label_height = 28
    cell_height = max(image.height for image in thumbs) + label_height
    contact = Image.new("RGB", (columns * thumb_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(contact)
    for index, image in enumerate(thumbs):
        x = (index % columns) * thumb_width
        y = (index // columns) * cell_height + label_height
        draw.text((x + 8, y - 22), f"{source.name} page {index + 1}", fill="#111111")
        contact.paste(image, (x, y))
    contact_path = output / f"{source.stem}-contact.png"
    contact.save(contact_path, format="PNG", optimize=False)
    return {
        "source": source.name, "pages": len(document), "rendered_pages": len(page_paths),
        "blank_pages": blank_pages, "contact_sheet": contact_path.name,
        "minimum_width": min(Image.open(path).width for path in page_paths),
        "minimum_height": min(Image.open(path).height for path in page_paths),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = [
        render_pdf(root / "reports" / "credit_memo.pdf", output),
        render_pdf(root / "reports" / "committee_brief.pdf", output),
    ]
    if any(row["blank_pages"] or row["pages"] != row["rendered_pages"] for row in results):
        raise SystemExit("PDF render QA failed")
    print(json.dumps({"status": "PASS", "renderer": "pypdfium2 5.13.0 / PDFium 153.0.7999.0", "documents": results}, sort_keys=True))


if __name__ == "__main__":
    main()
