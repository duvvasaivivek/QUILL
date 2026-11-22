from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


def report_pdf(report, period):
    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=landscape(A4), leftMargin=26, rightMargin=26,
                                 topMargin=26, bottomMargin=35, title=f"QUILL | {report.title}")
    styles = getSampleStyleSheet()
    cell_style = styles["BodyText"].clone("Cell", fontSize=8, leading=10, spaceBefore=0)
    header_style = cell_style.clone("Header", textColor=colors.white, fontName="Helvetica-Bold")

    def paragraph(value, style=cell_style):
        return Paragraph(escape(str(value)) if value is not None else "", style)

    label = f"As of {period.end}" if report.as_of else f"{period.start} to {period.end}"
    story = [paragraph(report.title, styles["Title"]), paragraph(label, styles["Normal"])]
    if period.customer:
        story.append(paragraph(f"Customer: {period.customer}", styles["Normal"]))
    if period.item:
        story.append(paragraph(f"{report.item_label}: {period.item}", styles["Normal"]))
    if report.note:
        story.append(paragraph(report.note, styles["Normal"]))
    story.append(Spacer(1, 12))
    table_rows = [[paragraph(column, header_style) for column in report.columns]]
    table_rows.extend([paragraph(value) for value in row] for row in report.rows(period))
    if len(table_rows) == 1:
        story.append(paragraph("No results."))
    else:
        weights = [
            1.5 if any(word in column.lower() for word in ("sku", "invoice", "reference", "customer", "product"))
            else 1 for column in report.columns
        ]
        widths = [(document.width - 12) * weight / sum(weights) for weight in weights]
        table = LongTable(table_rows, colWidths=widths,
                          repeatRows=1, splitInRow=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#153756")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eff4f8")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(26, 18, f"QUILL | {report.title}")
        canvas.drawRightString(doc.pagesize[0] - 26, 18, f"Page {doc.page}")

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
