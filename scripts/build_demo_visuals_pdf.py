"""Build a self-contained PDF from the retained demo prompts and figures."""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/DEMO_VISUELS_ET_PROMPTS.md"
OUTPUT = ROOT / "output/pdf/DEMO_VISUELS_ET_PROMPTS.pdf"

BLUE = colors.HexColor("#17365D")
MID_BLUE = colors.HexColor("#315D7A")
PALE_BLUE = colors.HexColor("#EEF5FB")
TEXT = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#475569")


def clean_markup(text: str) -> str:
    """Convert the small Markdown subset used by the source to ReportLab markup."""
    text = text.strip()
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("—", "-").replace("–", "-").replace("−", "-")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r'<font name="Courier">\1</font>', text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"<u>\1</u>", text)
    return text


def image_flowable(path: Path, max_width: float, max_height: float) -> Image:
    reader = ImageReader(str(path))
    width, height = reader.getSize()
    scale = min(max_width / width, max_height / height)
    return Image(str(path), width=width * scale, height=height * scale)


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.line(doc.leftMargin, 1.5 * cm, A4[0] - doc.rightMargin, 1.5 * cm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(doc.leftMargin, 1.05 * cm, "IDEA - Demonstration : prompts et visuels retenus")
    canvas.drawRightString(A4[0] - doc.rightMargin, 1.05 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=1.55 * cm,
        leftMargin=1.55 * cm,
        topMargin=1.65 * cm,
        bottomMargin=2.0 * cm,
        title="Demonstration IDEA - prompts et visuels retenus",
        author="IDEA - NeoLab",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DemoTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=27,
        alignment=TA_CENTER,
        textColor=BLUE,
        spaceAfter=14,
    )
    h1_style = ParagraphStyle(
        "Scenario",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=BLUE,
        spaceBefore=10,
        spaceAfter=9,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=MID_BLUE,
        spaceBefore=9,
        spaceAfter=5,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.4,
        leading=13,
        textColor=TEXT,
        spaceAfter=6,
        alignment=TA_LEFT,
    )
    prompt_style = ParagraphStyle(
        "Prompt",
        parent=body_style,
        leftIndent=7,
        rightIndent=7,
        spaceAfter=3,
    )
    caption_style = ParagraphStyle(
        "Caption",
        parent=body_style,
        fontName="Helvetica-Oblique",
        fontSize=8.7,
        leading=11,
        textColor=MUTED,
        spaceBefore=3,
        spaceAfter=8,
    )
    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.white,
        spaceAfter=0,
    )
    note_style = ParagraphStyle(
        "Note",
        parent=body_style,
        backColor=PALE_BLUE,
        borderColor=colors.HexColor("#B8D6F0"),
        borderWidth=0.6,
        borderPadding=7,
        spaceBefore=5,
        spaceAfter=9,
    )

    story = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    table_rows: list[list[str]] = []
    first_scenario = True

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines)
            style = note_style if text.startswith("**À dire.") else body_style
            story.append(Paragraph(clean_markup(text), style))
            paragraph_lines.clear()

    def flush_list() -> None:
        if list_items:
            flowable = ListFlowable(
                [ListItem(Paragraph(clean_markup(item), prompt_style)) for item in list_items],
                bulletType="1",
                start="1",
                leftIndent=17,
                bulletFontName="Helvetica-Bold",
                bulletFontSize=9,
            )
            story.append(flowable)
            story.append(Spacer(1, 5))
            list_items.clear()

    def flush_table() -> None:
        if len(table_rows) >= 2:
            filtered = [row for row in table_rows if not all(set(cell) <= {"-", ":"} for cell in row)]
            if filtered:
                rendered = [
                    [Paragraph(clean_markup(cell), table_header_style if index == 0 else body_style) for cell in row]
                    for index, row in enumerate(filtered)
                ]
                table = Table(rendered, hAlign="LEFT", repeatRows=1)
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                            ("TOPPADDING", (0, 0), (-1, -1), 5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ]
                    )
                )
                story.append(table)
                story.append(Spacer(1, 8))
        table_rows.clear()

    for raw_line in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        image_match = re.fullmatch(r"!\[([^\]]+)\]\(([^)]+)\)", line.strip())
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        numbered_match = re.match(r"^\d+\.\s+(.+)$", line)
        table_match = line.strip().startswith("|") and line.strip().endswith("|")

        if heading_match:
            flush_paragraph()
            flush_list()
            flush_table()
            level, title = heading_match.groups()
            if len(level) == 1:
                story.append(Paragraph(clean_markup(title), title_style))
                story.append(Spacer(1, 7))
            elif len(level) == 2:
                if not first_scenario:
                    story.append(PageBreak())
                first_scenario = False
                story.append(Paragraph(clean_markup(title), h1_style))
            else:
                story.append(Paragraph(clean_markup(title), h2_style))
            continue

        if image_match:
            flush_paragraph()
            flush_list()
            flush_table()
            caption, relative_path = image_match.groups()
            image_path = (SOURCE.parent / relative_path).resolve()
            if not image_path.is_file():
                raise FileNotFoundError(f"Image missing from demo PDF: {image_path}")
            figure = image_flowable(image_path, document.width, 14.3 * cm)
            story.append(KeepTogether([figure, Paragraph(clean_markup(caption), caption_style)]))
            continue

        if table_match:
            flush_paragraph()
            flush_list()
            table_rows.append([cell.strip() for cell in line.strip()[1:-1].split("|")])
            continue
        flush_table()

        if numbered_match:
            flush_paragraph()
            list_items.append(numbered_match.group(1))
            continue
        if list_items and raw_line.startswith((" ", "\t")) and line.strip():
            list_items[-1] = f"{list_items[-1]} {line.strip()}"
            continue
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue
        if line.strip() == "---":
            flush_paragraph()
            flush_list()
            story.append(Spacer(1, 8))
            continue
        if line.startswith("> "):
            flush_paragraph()
            story.append(Paragraph(clean_markup(line[2:]), note_style))
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    flush_list()
    flush_table()
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    build_pdf()
