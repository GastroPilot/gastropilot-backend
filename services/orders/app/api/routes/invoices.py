"""Invoice/receipt PDF generation endpoint."""

from __future__ import annotations

import io
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_staff_or_above
from app.models.order import Order, OrderItem, SumUpPayment

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("/{order_id}/pdf")
async def generate_invoice_pdf(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_staff_or_above),
):
    # Load order
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Load items
    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.sort_order)
    )
    items = items_result.scalars().all()

    # Load SumUp payment if exists
    payment_result = await db.execute(
        select(SumUpPayment)
        .where(SumUpPayment.order_id == order_id)
        .order_by(SumUpPayment.created_at.desc())
    )
    payment = payment_result.scalars().first()

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
        from reportlab.platypus import Table as RLTable
        from reportlab.platypus import (
            TableStyle,
        )
    except ImportError:
        raise HTTPException(status_code=500, detail="ReportLab not installed")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    story = []

    # Header
    story.append(Paragraph(f"Beleg Nr. {order.order_number or order_id}", styles["Title"]))
    story.append(Spacer(1, 5 * mm))

    if order.opened_at:
        story.append(
            Paragraph(f"Datum: {order.opened_at.strftime('%d.%m.%Y %H:%M')}", styles["Normal"])
        )
    story.append(Spacer(1, 5 * mm))

    # Items table
    table_data = [["Artikel", "Menge", "Einzelpreis", "MwSt", "Gesamt"]]
    for item in items:
        tax_pct = f"{int(item.tax_rate * 100)}%"
        table_data.append(
            [
                item.item_name,
                str(item.quantity),
                f"{item.unit_price:.2f} EUR",
                tax_pct,
                f"{item.total_price:.2f} EUR",
            ]
        )

    if table_data:
        t = RLTable(table_data, colWidths=[200, 50, 80, 50, 80])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ]
            )
        )
        story.append(t)

    story.append(Spacer(1, 5 * mm))

    # Totals
    totals = [
        ["Zwischensumme:", f"{order.subtotal:.2f} EUR"],
    ]
    if order.discount_amount > 0:
        totals.append(["Rabatt:", f"-{order.discount_amount:.2f} EUR"])
    if order.tax_amount_7 > 0:
        totals.append(["MwSt. 7%:", f"{order.tax_amount_7:.2f} EUR"])
    if order.tax_amount_19 > 0:
        totals.append(["MwSt. 19%:", f"{order.tax_amount_19:.2f} EUR"])
    if order.tip_amount > 0:
        totals.append(["Trinkgeld:", f"{order.tip_amount:.2f} EUR"])
    totals.append(["Gesamtbetrag:", f"{order.total:.2f} EUR"])

    totals_table = RLTable(totals, colWidths=[350, 110])
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
            ]
        )
    )
    story.append(totals_table)

    # Payment info
    story.append(Spacer(1, 5 * mm))
    pay_method = order.payment_method or "N/A"
    story.append(Paragraph(f"Zahlungsart: {pay_method}", styles["Normal"]))
    story.append(Paragraph(f"Zahlungsstatus: {order.payment_status}", styles["Normal"]))

    if payment and payment.transaction_code:
        story.append(Spacer(1, 3 * mm))
        story.append(
            Paragraph(f"SumUp Transaktionscode: {payment.transaction_code}", styles["Normal"])
        )

    # TSE / fiskaly data
    from app.models.fiskaly import FiskalyTransaction

    tse_result = await db.execute(
        select(FiskalyTransaction)
        .where(
            FiskalyTransaction.order_id == order_id,
            FiskalyTransaction.tx_state == "FINISHED",
        )
        .order_by(FiskalyTransaction.created_at.desc())
    )
    tse_tx = tse_result.scalars().first()

    if tse_tx:
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("TSE-Daten", styles["Heading4"]))

        tse_data = []
        if tse_tx.tss_serial_number:
            tse_data.append(["TSE-Seriennummer:", tse_tx.tss_serial_number[:40]])
        if tse_tx.tx_number is not None:
            tse_data.append(["TSE-Transaktion:", str(tse_tx.tx_number)])
        if tse_tx.signature_value:
            sig_short = tse_tx.signature_value[:40] + "..."
            tse_data.append(["TSE-Signatur:", sig_short])
        if tse_tx.time_start:
            from datetime import UTC as _UTC
            from datetime import datetime as dt

            ts_start = dt.fromtimestamp(tse_tx.time_start, tz=_UTC)
            tse_data.append(["TSE-Start:", ts_start.strftime("%d.%m.%Y %H:%M:%S")])
        if tse_tx.time_end:
            ts_end = dt.fromtimestamp(tse_tx.time_end, tz=_UTC)
            tse_data.append(["TSE-Stop:", ts_end.strftime("%d.%m.%Y %H:%M:%S")])
        if tse_tx.client_serial_number:
            tse_data.append(["KassenID:", tse_tx.client_serial_number])

        if tse_data:
            tse_table = RLTable(tse_data, colWidths=[120, 340])
            tse_table.setStyle(
                TableStyle(
                    [
                        ("FONTSIZE", (0, 0), (-1, -1), 7),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(tse_table)

        # QR code
        if tse_tx.qr_code_data:
            try:
                from reportlab.graphics.barcode.qr import QrCodeWidget
                from reportlab.graphics.shapes import Drawing

                qr_size = 40 * mm
                qr = QrCodeWidget(tse_tx.qr_code_data, barWidth=qr_size, barHeight=qr_size)
                drawing = Drawing(qr_size, qr_size)
                drawing.add(qr)
                story.append(Spacer(1, 3 * mm))
                story.append(drawing)
            except Exception as exc:
                import logging

                logging.getLogger(__name__).error("QR code render failed: %s", exc)
                story.append(Paragraph("(QR-Code nicht verfügbar)", styles["Normal"]))

    doc.build(story)
    buffer.seek(0)

    filename = f"beleg-{order.order_number or order_id}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
