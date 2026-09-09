import json
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent


def generate():
    data = json.loads((ROOT / "sample-data/scenario.json").read_text())
    destination = ROOT / "sample-data/pdfs"
    destination.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 11
    styles["BodyText"].leading = 17
    styles["Title"].textColor = colors.HexColor("#236648")
    manifest = {"documents": []}
    for entry in data["documents"]:
        path = destination / entry["filename"]
        story = []
        for number, page in enumerate(entry["pages"], start=1):
            if number > 1:
                story.append(PageBreak())
            story.append(Paragraph("SYNTHETISCHE DEMODATEN - KEINE REALEN UNTERNEHMENSDATEN", styles["Heading3"]))
            story.append(Spacer(1, 0.6 * cm))
            story.append(Paragraph(escape(entry["title"]), styles["Title"]))
            story.append(Paragraph(f"{entry['document_id']} | {data['date']} | Seite {number}", styles["BodyText"]))
            story.append(Spacer(1, cm))
            story.append(Paragraph(escape(page["heading"]), styles["Heading2"]))
            for text in page["paragraphs"]:
                story.append(Paragraph(escape(text), styles["BodyText"]))
                story.append(Spacer(1, 0.4 * cm))
        document = SimpleDocTemplate(str(path), rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm, title=entry["title"], author=data["company"], invariant=1)
        document.build(story)
        reader = PdfReader(path)
        assert len(reader.pages) == len(entry["pages"])
        assert all("SYNTHETISCHE DEMODATEN" in page.extract_text() for page in reader.pages)
        manifest["documents"].append({key: entry[key] for key in ("document_id", "filename", "title")})
        print(f"Generated {entry['filename']}: {len(reader.pages)} pages")
    (ROOT / "sample-data/corpus-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    image = Image.new("RGB", (960, 560), "#edf4ef")
    drawing = ImageDraw.Draw(image)
    font = ImageFont.truetype("DejaVuSans.ttf", 32)
    small = ImageFont.truetype("DejaVuSans.ttf", 22)
    drawing.rectangle((40, 40, 920, 520), fill="white", outline="#b6c5bc", width=2)
    drawing.rectangle((40, 40, 920, 55), fill="#236648")
    drawing.text((80, 95), data["company"], fill="#236648", font=font)
    drawing.text((80, 170), "Vorausschauende Instandhaltung", fill="#222822", font=font)
    drawing.text((80, 245), "Vollprogramm    CHF 24 Mio.", fill="#176d83", font=font)
    drawing.text((80, 300), "Gestufter Pilot   CHF 8 Mio.", fill="#176d83", font=font)
    drawing.text((80, 385), "6 Perspektiven | 12 Seiten | September 2026", fill="#59625b", font=small)
    drawing.text((80, 445), "SYNTHETISCHE DEMODATEN", fill="#59625b", font=small)
    image.save(ROOT / "app/static/briefing.png")


if __name__ == "__main__":
    generate()