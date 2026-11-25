from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#102743")
BLUE = colors.HexColor("#174A80")
LINE = colors.HexColor("#DCE5ED")
SOFT = colors.HexColor("#F2F6FA")
MUTED = colors.HexColor("#40576C")


def number(value):
    return "0.00" if not value else f"{value:,.2f}"


def quantity(value):
    return f"{value:f}".rstrip("0").rstrip(".") if value % 1 else f"{value:.0f}"


def state_label(snapshot):
    return " / ".join(str(value) for value in (
        snapshot.get("state_name"), snapshot.get("state_code"),
    ) if value) or "Unavailable"


def render_invoice(invoice, *, credit_note=None):
    stream = BytesIO()
    title = "GST credit note" if credit_note else "GST tax invoice"
    issued = credit_note or invoice
    document = SimpleDocTemplate(
        stream, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=37, bottomMargin=47,
        title=f"{title} {issued.number}",
    )
    width = document.width - 12
    normal = ParagraphStyle("Normal", fontName="Helvetica", fontSize=9, leading=13, textColor=INK)
    small = ParagraphStyle("Small", parent=normal, fontSize=8, leading=11)
    header = ParagraphStyle("Header", parent=small, textColor=colors.white, fontName="Helvetica-Bold")
    numeric = ParagraphStyle("Numeric", parent=small, alignment=2)
    h1 = ParagraphStyle("Title", parent=normal, fontName="Helvetica-Bold", fontSize=24, leading=28)

    def paragraph(value, style=normal):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)

    def info(label, snapshot, *, seller=False):
        lines = [f"<b>{label}</b>"]
        if not snapshot:
            lines.append("No supplier snapshot was recorded when this invoice was issued.")
        else:
            fields = (snapshot.get("name"), snapshot.get("address"), state_label(snapshot),
                      "GSTIN: " + (snapshot.get("gstin") or ("Unavailable" if seller else "Not provided")))
            lines.extend(escape(str(value)).replace("\n", "<br/>") for value in fields if value)
        return Paragraph("<br/>".join(lines), normal)

    story = [paragraph(title, h1), Spacer(1, 3),
             paragraph(f"{issued.number}  |  Issued {timezone.localdate(issued.issued_at):%d %b %Y}"),
             Spacer(1, 11)]
    if credit_note:
        story += [paragraph(f"Original invoice: {invoice.number}"), paragraph(f"Reason: {credit_note.reason}"), Spacer(1, 8)]
    elif hasattr(invoice, "credit_note"):
        story += [paragraph(f"Cancelled by {invoice.credit_note.number}"), Spacer(1, 8)]
    parties = Table([[info("Supplier", invoice.issuer_snapshot, seller=True), info("Bill to", invoice.customer_snapshot)]],
                    colWidths=[width / 2] * 2, style=[
                        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ])
    story += [parties, Spacer(1, 9), paragraph(f"Place of supply: {state_label(invoice.customer_snapshot)}"),
              paragraph("All amounts are in INR."), Spacer(1, 8)]
    columns = ("Product / HSN", "Qty", "Rate", "Taxable", "GST %", "CGST", "SGST", "IGST", "Total")
    fractions = (0.24, 0.065, 0.09, 0.105, 0.07, 0.10, 0.10, 0.10, 0.13)
    weights = sum(fractions)
    rows = [[paragraph(column, header) for column in columns]]
    sign = -1 if credit_note else 1
    for line in invoice.lines.order_by("pk").iterator():
        description = escape(line.description)
        hsn = escape(line.hsn or "Unavailable")
        item = Paragraph(f"{description}<br/><font color='#40576C'>HSN {hsn}</font>", small)
        amounts = (quantity(line.quantity * sign), number(line.unit_price), number(line.taxable * sign),
                   quantity(line.gst_rate), number(line.cgst * sign), number(line.sgst * sign),
                   number(line.igst * sign), number((line.taxable + line.cgst + line.sgst + line.igst) * sign))
        rows.append([item, *(paragraph(amount, numeric) for amount in amounts)])
    detail = LongTable(rows, colWidths=[width * part / weights for part in fractions], repeatRows=1, splitInRow=1)
    detail.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SOFT]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, LINE),
    ]))
    story += [detail, Spacer(1, 12)]
    totals = [("Taxable", invoice.taxable), ("CGST", invoice.cgst), ("SGST", invoice.sgst),
              ("IGST", invoice.igst), ("Credit total" if credit_note else "Invoice total", invoice.total)]
    total_rows = [[label, number(value * sign)] for label, value in totals]
    summary = Table(total_rows, colWidths=[99, 82], hAlign="RIGHT")
    summary.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, -1), (-1, -1), SOFT),
    ]))
    story.append(summary)
    if not credit_note:
        story += [Spacer(1, 6), paragraph(f"Outstanding at download: INR {number(invoice.outstanding)}", numeric)]

    def footer(canvas, doc):
        canvas.setStrokeColor(LINE)
        canvas.line(36, 36, A4[0] - 36, 36)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(36, 24, f"QUILL  |  {issued.number}")
        canvas.drawRightString(A4[0] - 36, 24, f"Page {doc.page}")

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
