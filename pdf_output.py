from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

from pathlib import Path
import logging
logger = logging.getLogger(__name__)

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

def register_cjk_font():
    """Uses ReportLab's built-in CID font — no external font file needed."""
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    logger.info("[PDF] Using built-in CID font STSong-Light for CJK support.")
    return "STSong-Light"

def save_pipeline_to_pdf(compiled_rows, output_pdf_path, MANIFEST_DATE):
    """
    Renders the compiled manifest rows as a formatted landscape PDF table.
    Handles Chinese characters and long cell text via word-wrapped Paragraphs.
    """
    if not compiled_rows:
        logger.error("PDF Output Stage aborted: No data rows found to write.")
        return False
    
    cjk_font = register_cjk_font()  # <-- add this

    logger.info(f"Starting PDF export: {len(compiled_rows) - 1} records to {output_pdf_path}...")

    try:
        pdf_file = Path(output_pdf_path)
        pdf_file.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(pdf_file),
            pagesize=landscape(A4),
            leftMargin=10*mm,
            rightMargin=10*mm,
            topMargin=12*mm,
            bottomMargin=12*mm,
        )

        styles = getSampleStyleSheet()
        cell_style = ParagraphStyle(
            "cell",
            parent=styles["Normal"],
            fontSize=6.5,
            leading=9,
            fontName=cjk_font,
            wordWrap="CJK",   # Handles Chinese text line-breaking correctly
        )
        header_style = ParagraphStyle(
            "header",
            parent=styles["Normal"],
            fontSize=7,
            leading=9,
            fontName=cjk_font,
            alignment=TA_CENTER,
        )

        # Wrap every cell in a Paragraph so long text wraps instead of overflowing
        def wrap_row(row, style):
            return [Paragraph(str(cell) if cell else "", style) for cell in row]

        table_data = [wrap_row(compiled_rows[0], header_style)]
        for row in compiled_rows[1:]:
            table_data.append(wrap_row(row, cell_style))

        # Distribute column widths across the landscape page (~277mm usable)
        num_cols = len(compiled_rows[0])
        col_width = (277 * mm) / num_cols
        col_widths = [col_width] * num_cols

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            # Header row
            ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor("#2C3E50")),
            ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
            ("ALIGN",       (0, 0), (-1, 0),  "CENTER"),
            ("VALIGN",      (0, 0), (-1, -1), "TOP"),
            # Alternating row shading
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            # Grid
            ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
            ("LINEBELOW",   (0, 0), (-1, 0),  1.2, colors.HexColor("#1A252F")),
            # Padding
            ("TOPPADDING",  (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING",(0, 0), (-1, -1), 3),
        ]))

        title_style = ParagraphStyle(
            "title", parent=styles["Normal"],
            fontSize=11, fontName="Helvetica-Bold",
            spaceBefore=0, spaceAfter=6,
        )
        title = Paragraph(f"Flight Manifest — {MANIFEST_DATE or 'Date TBD'}", title_style)

        doc.build([title, Spacer(1, 4*mm), table])
        logger.info("✅ PDF Export Complete!")
        return True

    except Exception as e:
        logger.error(f"❌ PDF export failed: {e}")
        return False