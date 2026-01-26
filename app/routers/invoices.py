"""
Invoice Router - PDF Generation für Rechnungen
"""

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, OrderItem, Restaurant
from app.database.models import Table as TableModel
from app.dependencies import User, get_session, require_mitarbeiter_role, require_orders_module

router = APIRouter(prefix="/restaurants/{restaurant_id}/invoices", tags=["invoices"])


async def _get_restaurant_or_404(restaurant_id: int, session: AsyncSession) -> Restaurant:
    """Holt ein Restaurant oder wirft 404."""
    from app.database.models import Restaurant

    restaurant = await session.get(Restaurant, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


async def _get_order_or_404(order_id: int, restaurant_id: int, session: AsyncSession) -> Order:
    """Holt eine Bestellung oder wirft 404."""
    result = await session.execute(
        select(Order).where(Order.id == order_id, Order.restaurant_id == restaurant_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.get("/{order_id}/pdf", dependencies=[Depends(require_orders_module)])
async def generate_invoice_pdf(
    restaurant_id: int,
    order_id: int,
    session: AsyncSession = Depends(get_session),
    _license: User = Depends(require_orders_module),
    current_user: User = Depends(require_mitarbeiter_role),
):
    """Generiert ein PDF der Rechnung für eine Bestellung."""
    try:
        restaurant = await _get_restaurant_or_404(restaurant_id, session)
        order = await _get_order_or_404(order_id, restaurant_id, session)

        # Lade OrderItems
        result = await session.execute(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.sort_order, OrderItem.id)
        )
        items = result.scalars().all()

        # Lade Tisch-Informationen falls vorhanden
        table_number = None
        if order.table_id:
            table_result = await session.execute(
                select(TableModel).where(TableModel.id == order.table_id)
            )
            table_obj = table_result.scalar_one_or_none()
            if table_obj:
                table_number = table_obj.number

        # Erstelle PDF im Speicher
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=15 * mm,
            leftMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        # Styles
        styles = getSampleStyleSheet()

        # Restaurant Header Style
        restaurant_name_style = ParagraphStyle(
            "RestaurantName",
            parent=styles["Heading1"],
            fontSize=28,
            textColor=colors.HexColor("#000000"),
            spaceAfter=6,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
        )

        restaurant_info_style = ParagraphStyle(
            "RestaurantInfo",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#333333"),
            alignment=TA_CENTER,
            spaceAfter=2,
            fontName="Helvetica",
        )

        # Invoice Title Style
        invoice_title_style = ParagraphStyle(
            "InvoiceTitle",
            parent=styles["Heading2"],
            fontSize=20,
            textColor=colors.HexColor("#000000"),
            spaceAfter=20,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
        )

        # Order Info Style
        order_info_style = ParagraphStyle(
            "OrderInfo",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#666666"),
            spaceAfter=4,
            fontName="Helvetica",
        )

        # Normal text style
        normal_style = ParagraphStyle(
            "NormalText",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#000000"),
            fontName="Helvetica",
        )

        # Payment info style
        payment_info_style = ParagraphStyle(
            "PaymentInfo",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#000000"),
            spaceAfter=3,
            fontName="Helvetica",
        )

        # Footer style
        footer_style = ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#666666"),
            alignment=TA_CENTER,
            fontName="Helvetica",
        )

        story = []

        # Restaurant Header
        story.append(Paragraph(restaurant.name or "Restaurant", restaurant_name_style))
        if restaurant.address:
            story.append(Paragraph(restaurant.address, restaurant_info_style))
        if restaurant.phone:
            story.append(Paragraph(f"Tel: {restaurant.phone}", restaurant_info_style))
        if restaurant.email:
            story.append(Paragraph(f"E-Mail: {restaurant.email}", restaurant_info_style))

        story.append(Spacer(1, 8 * mm))

        # Separator Line
        story.append(
            HRFlowable(width="100%", thickness=1, lineCap="round", color=colors.HexColor("#000000"))
        )
        story.append(Spacer(1, 8 * mm))

        # Invoice Title
        story.append(Paragraph("RECHNUNG", invoice_title_style))

        # Order Information
        order_info_data = []
        order_info_data.append(
            [
                Paragraph(
                    f"<b>Bestellnummer:</b> {order.order_number or f'#{order.id}'}",
                    order_info_style,
                ),
                Paragraph(
                    f"<b>Datum:</b> {order.opened_at.strftime('%d.%m.%Y')}", order_info_style
                ),
            ]
        )
        order_info_data.append(
            [
                Paragraph(
                    f"<b>Uhrzeit:</b> {order.opened_at.strftime('%H:%M')} Uhr", order_info_style
                ),
                Paragraph(
                    f"<b>Rechnungsdatum:</b> {order.paid_at.strftime('%d.%m.%Y') if order.paid_at else order.opened_at.strftime('%d.%m.%Y')}",
                    order_info_style,
                ),
            ]
        )
        if table_number:
            # Tischname formatieren (vermeide "Tisch Tisch 2")
            table_display = (
                table_number
                if str(table_number).lower().startswith("tisch")
                else f"Tisch {table_number}"
            )
            order_info_data.append(
                [
                    Paragraph(f"<b>{table_display}</b>", order_info_style),
                    Paragraph(
                        f"<b>Personen:</b> {order.party_size}" if order.party_size else "",
                        order_info_style,
                    ),
                ]
            )

        order_info_table = Table(order_info_data, colWidths=[85 * mm, 85 * mm])
        order_info_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(order_info_table)
        story.append(Spacer(1, 10 * mm))

        # Items Table
        data = [["Artikel", "Menge", "Einzelpreis", "Gesamtpreis"]]
        for item in items:
            item_name = item.item_name or ""
            if item.item_description:
                item_name += f"<br/><font size='8' color='#666666'>{item.item_description}</font>"
            data.append(
                [
                    Paragraph(item_name, normal_style),
                    Paragraph(str(item.quantity), normal_style),
                    Paragraph(f"{item.unit_price:.2f} €", normal_style),
                    Paragraph(f"{item.total_price:.2f} €", normal_style),
                ]
            )
            if item.notes:
                data.append(
                    [
                        Paragraph(
                            f"<i>└ {item.notes}</i>",
                            ParagraphStyle(
                                "ItemNote",
                                parent=normal_style,
                                fontSize=9,
                                textColor=colors.HexColor("#666666"),
                                leftIndent=10,
                            ),
                        ),
                        "",
                        "",
                        "",
                    ]
                )

        # Summary rows
        summary_start_row = len(data)
        data.append(["", "", "", ""])  # Empty row for spacing
        data.append(
            [
                "",
                "",
                Paragraph("Zwischensumme:", normal_style),
                Paragraph(f"{order.subtotal:.2f} €", normal_style),
            ]
        )
        if order.discount_amount > 0:
            discount_label = "Rabatt"
            if order.discount_percentage:
                discount_label += f" ({order.discount_percentage}%)"
            data.append(
                [
                    "",
                    "",
                    Paragraph(discount_label + ":", normal_style),
                    Paragraph(f"-{order.discount_amount:.2f} €", normal_style),
                ]
            )
        # MwSt-Aufschlüsselung nach Steuersätzen
        if order.tax_amount_7 and order.tax_amount_7 > 0:
            data.append(
                [
                    "",
                    "",
                    Paragraph("MwSt. (7%):", normal_style),
                    Paragraph(f"{order.tax_amount_7:.2f} €", normal_style),
                ]
            )
        if order.tax_amount_19 and order.tax_amount_19 > 0:
            data.append(
                [
                    "",
                    "",
                    Paragraph("MwSt. (19%):", normal_style),
                    Paragraph(f"{order.tax_amount_19:.2f} €", normal_style),
                ]
            )
        if (
            order.tax_amount > 0
            and (not order.tax_amount_7 or order.tax_amount_7 == 0)
            and (not order.tax_amount_19 or order.tax_amount_19 == 0)
        ):
            # Fallback für alte Bestellungen ohne Aufschlüsselung
            data.append(
                [
                    "",
                    "",
                    Paragraph("MwSt.:", normal_style),
                    Paragraph(f"{order.tax_amount:.2f} €", normal_style),
                ]
            )
        if order.tip_amount and order.tip_amount > 0:
            data.append(
                [
                    "",
                    "",
                    Paragraph("Trinkgeld:", normal_style),
                    Paragraph(f"{order.tip_amount:.2f} €", normal_style),
                ]
            )

        # Total row with bold style
        total_style = ParagraphStyle(
            "TotalStyle",
            parent=normal_style,
            fontSize=12,
            fontName="Helvetica-Bold",
        )
        data.append(
            [
                "",
                "",
                Paragraph("<b>GESAMT:</b>", total_style),
                Paragraph(f"<b>{order.total:.2f} €</b>", total_style),
            ]
        )

        items_table = Table(data, colWidths=[90 * mm, 25 * mm, 30 * mm, 25 * mm])
        items_table.setStyle(
            TableStyle(
                [
                    # Header row
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#000000")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 11),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                    ("TOPPADDING", (0, 0), (-1, 0), 10),
                    ("ALIGN", (0, 0), (0, 0), "LEFT"),
                    ("ALIGN", (1, 0), (-1, 0), "CENTER"),
                    # Data rows
                    ("FONTNAME", (0, 1), (-1, summary_start_row - 1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, summary_start_row - 1), 10),
                    ("TOPPADDING", (0, 1), (-1, summary_start_row - 1), 6),
                    ("BOTTOMPADDING", (0, 1), (-1, summary_start_row - 1), 6),
                    ("ALIGN", (1, 1), (1, -1), "CENTER"),
                    ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    # Grid
                    ("LINEBELOW", (0, 0), (-1, 0), 1, colors.white),
                    (
                        "LINEBELOW",
                        (0, summary_start_row - 1),
                        (-1, summary_start_row - 1),
                        1,
                        colors.HexColor("#cccccc"),
                    ),
                    # Total row
                    ("LINEABOVE", (0, -1), (-1, -1), 2, colors.HexColor("#000000")),
                    ("TOPPADDING", (0, -1), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f5f5f5")),
                ]
            )
        )

        story.append(items_table)
        story.append(Spacer(1, 12 * mm))

        # Payment Information
        if order.payment_status == "paid":
            payment_info = []
            payment_info.append(Paragraph("<b>Zahlungsstatus: Bezahlt</b>", payment_info_style))
            if order.paid_at:
                payment_info.append(
                    Paragraph(
                        f"Bezahlt am: {order.paid_at.strftime('%d.%m.%Y um %H:%M')} Uhr",
                        payment_info_style,
                    )
                )
            payment_methods = {
                "cash": "Bar",
                "card": "Karte",
                "sumup_card": "SumUp Terminal",
                "split": "Geteilt",
            }
            if order.payment_method:
                payment_info.append(
                    Paragraph(
                        f"Zahlungsmethode: {payment_methods.get(order.payment_method, order.payment_method)}",
                        payment_info_style,
                    )
                )

            # SumUp Transaction Info hinzufügen, falls vorhanden
            if order.payment_method == "sumup_card":
                # Lade SumUp Payment Info
                from app.database.models import SumUpPayment

                sumup_result = await session.execute(
                    select(SumUpPayment)
                    .where(SumUpPayment.order_id == order_id)
                    .where(SumUpPayment.status == "successful")
                    .order_by(SumUpPayment.completed_at.desc())
                )
                sumup_payment = sumup_result.scalar_one_or_none()
                if sumup_payment:
                    if sumup_payment.transaction_code:
                        payment_info.append(
                            Paragraph(
                                f"SumUp Transaction: {sumup_payment.transaction_code}",
                                payment_info_style,
                            )
                        )
                    if sumup_payment.checkout_id:
                        payment_info.append(
                            Paragraph(
                                f"SumUp Checkout ID: {sumup_payment.checkout_id[:20]}...",
                                payment_info_style,
                            )
                        )
            if order.split_payments:
                payment_info.append(Paragraph("<b>Zahlungsaufteilung:</b>", payment_info_style))
                split_payments_list = order.split_payments
                if isinstance(split_payments_list, str):
                    import json

                    split_payments_list = json.loads(split_payments_list)
                if isinstance(split_payments_list, list):
                    for payment in split_payments_list:
                        if isinstance(payment, dict):
                            method = payment_methods.get(
                                payment.get("method", ""), payment.get("method", "")
                            )
                            amount = payment.get("amount", 0)
                            payment_info.append(
                                Paragraph(f"  • {method}: {amount:.2f} €", payment_info_style)
                            )

            for info in payment_info:
                story.append(info)
                story.append(Spacer(1, 3 * mm))

        story.append(Spacer(1, 15 * mm))

        # SumUp Payment Info mit allen Transaktionsdaten (falls vorhanden)
        if order.payment_method == "sumup_card":
            from app.database.models import SumUpPayment

            sumup_result = await session.execute(
                select(SumUpPayment)
                .where(SumUpPayment.order_id == order_id)
                .where(SumUpPayment.status == "successful")
                .order_by(SumUpPayment.completed_at.desc())
            )
            sumup_payment = sumup_result.scalar_one_or_none()
            if sumup_payment:
                story.append(
                    HRFlowable(
                        width="100%",
                        thickness=0.5,
                        lineCap="round",
                        color=colors.HexColor("#cccccc"),
                    )
                )
                story.append(Spacer(1, 5 * mm))

                # SumUp Info Styles
                sumup_header_style = ParagraphStyle(
                    "SumUpHeader",
                    parent=styles["Normal"],
                    fontSize=11,
                    textColor=colors.HexColor("#000000"),
                    alignment=TA_CENTER,
                    fontName="Helvetica-Bold",
                    spaceAfter=8,
                )
                sumup_info_style = ParagraphStyle(
                    "SumUpInfo",
                    parent=styles["Normal"],
                    fontSize=9,
                    textColor=colors.HexColor("#666666"),
                    alignment=TA_CENTER,
                    fontName="Helvetica",
                    spaceAfter=3,
                )
                sumup_label_style = ParagraphStyle(
                    "SumUpLabel",
                    parent=styles["Normal"],
                    fontSize=9,
                    textColor=colors.HexColor("#000000"),
                    fontName="Helvetica-Bold",
                )
                sumup_value_style = ParagraphStyle(
                    "SumUpValue",
                    parent=styles["Normal"],
                    fontSize=9,
                    textColor=colors.HexColor("#666666"),
                    fontName="Helvetica",
                )

                story.append(Paragraph("<b>Zahlung über SumUp Terminal</b>", sumup_header_style))

                # Basis-Transaktionsdaten
                if sumup_payment.transaction_code:
                    story.append(
                        Paragraph(
                            f"Transaction Code: {sumup_payment.transaction_code}", sumup_info_style
                        )
                    )
                if sumup_payment.checkout_id:
                    story.append(
                        Paragraph(f"Checkout ID: {sumup_payment.checkout_id}", sumup_info_style)
                    )

                # Vollständige Receipt-Daten aus webhook_data
                receipt_data = None
                if sumup_payment.webhook_data:
                    receipt_data = sumup_payment.webhook_data.get("receipt_data")

                if receipt_data:
                    transaction_data = receipt_data.get("transaction_data", {})
                    acquirer_data = receipt_data.get("acquirer_data", {})
                    emv_data = receipt_data.get("emv_data", {})
                    merchant_data = receipt_data.get("merchant_data", {})

                    story.append(Spacer(1, 3 * mm))
                    story.append(
                        HRFlowable(
                            width="100%",
                            thickness=0.3,
                            lineCap="round",
                            color=colors.HexColor("#cccccc"),
                        )
                    )
                    story.append(Spacer(1, 3 * mm))

                    # Receipt Number
                    if transaction_data.get("receipt_no"):
                        story.append(
                            Paragraph(
                                f"<b>Belegnummer:</b> {transaction_data.get('receipt_no')}",
                                sumup_info_style,
                            )
                        )

                    # Transaktionsdetails
                    if transaction_data.get("timestamp"):
                        from datetime import datetime

                        try:
                            ts = datetime.fromisoformat(
                                transaction_data.get("timestamp").replace("Z", "+00:00")
                            )
                            story.append(
                                Paragraph(
                                    f"<b>Transaktionszeit:</b> {ts.strftime('%d.%m.%Y %H:%M:%S')} Uhr",
                                    sumup_info_style,
                                )
                            )
                        except:
                            story.append(
                                Paragraph(
                                    f"<b>Transaktionszeit:</b> {transaction_data.get('timestamp')}",
                                    sumup_info_style,
                                )
                            )

                    if transaction_data.get("payment_type"):
                        payment_types = {
                            "card": "Karte",
                            "boleto": "Boleto",
                            "ideal": "iDEAL",
                        }
                        pt = payment_types.get(
                            transaction_data.get("payment_type"),
                            transaction_data.get("payment_type"),
                        )
                        story.append(Paragraph(f"<b>Zahlungsart:</b> {pt}", sumup_info_style))

                    if transaction_data.get("entry_mode"):
                        entry_modes = {
                            "CHIP": "Chip",
                            "CONTACTLESS": "Kontaktlos",
                            "MAGSTRIPE": "Magnetstreifen",
                            "MANUAL": "Manuell",
                        }
                        em = entry_modes.get(
                            transaction_data.get("entry_mode"), transaction_data.get("entry_mode")
                        )
                        story.append(Paragraph(f"<b>Eingabemethode:</b> {em}", sumup_info_style))

                    if transaction_data.get("verification_method"):
                        verification_methods = {
                            "PIN": "PIN",
                            "SIGNATURE": "Unterschrift",
                            "NONE": "Keine",
                        }
                        vm = verification_methods.get(
                            transaction_data.get("verification_method"),
                            transaction_data.get("verification_method"),
                        )
                        story.append(Paragraph(f"<b>Verifizierung:</b> {vm}", sumup_info_style))

                    # Kartendaten
                    card_data = transaction_data.get("card", {})
                    if card_data:
                        if card_data.get("last_4_digits"):
                            story.append(
                                Paragraph(
                                    f"<b>Karte:</b> **** {card_data.get('last_4_digits')}",
                                    sumup_info_style,
                                )
                            )
                        if card_data.get("type"):
                            story.append(
                                Paragraph(
                                    f"<b>Kartentyp:</b> {card_data.get('type')}", sumup_info_style
                                )
                            )

                    # Acquirer Data (TSE-relevant)
                    if acquirer_data:
                        story.append(Spacer(1, 3 * mm))
                        story.append(
                            HRFlowable(
                                width="100%",
                                thickness=0.3,
                                lineCap="round",
                                color=colors.HexColor("#cccccc"),
                            )
                        )
                        story.append(Spacer(1, 3 * mm))
                        story.append(Paragraph("<b>TSE / Acquirer-Daten</b>", sumup_header_style))

                        if acquirer_data.get("tid"):
                            story.append(
                                Paragraph(
                                    f"<b>Terminal ID:</b> {acquirer_data.get('tid')}",
                                    sumup_info_style,
                                )
                            )
                        if acquirer_data.get("authorization_code"):
                            story.append(
                                Paragraph(
                                    f"<b>Autorisierungscode:</b> {acquirer_data.get('authorization_code')}",
                                    sumup_info_style,
                                )
                            )
                        if acquirer_data.get("return_code"):
                            story.append(
                                Paragraph(
                                    f"<b>Return Code:</b> {acquirer_data.get('return_code')}",
                                    sumup_info_style,
                                )
                            )
                        if acquirer_data.get("local_time"):
                            story.append(
                                Paragraph(
                                    f"<b>Lokale Zeit:</b> {acquirer_data.get('local_time')}",
                                    sumup_info_style,
                                )
                            )

                    # EMV Data (TSE-Daten, falls vorhanden)
                    if emv_data and isinstance(emv_data, dict) and len(emv_data) > 0:
                        story.append(Spacer(1, 3 * mm))
                        story.append(
                            HRFlowable(
                                width="100%",
                                thickness=0.3,
                                lineCap="round",
                                color=colors.HexColor("#cccccc"),
                            )
                        )
                        story.append(Spacer(1, 3 * mm))
                        story.append(Paragraph("<b>EMV / TSE-Daten</b>", sumup_header_style))

                        # Zeige alle EMV-Felder an
                        for key, value in emv_data.items():
                            if value:  # Nur wenn Wert vorhanden
                                story.append(Paragraph(f"<b>{key}:</b> {value}", sumup_info_style))

                    # VAT Rates (MwSt-Aufschlüsselung)
                    vat_rates = transaction_data.get("vat_rates", [])
                    if vat_rates:
                        story.append(Spacer(1, 3 * mm))
                        story.append(
                            HRFlowable(
                                width="100%",
                                thickness=0.3,
                                lineCap="round",
                                color=colors.HexColor("#cccccc"),
                            )
                        )
                        story.append(Spacer(1, 3 * mm))
                        story.append(
                            Paragraph("<b>MwSt-Aufschlüsselung (SumUp)</b>", sumup_header_style)
                        )
                        for vat_rate in vat_rates:
                            rate = vat_rate.get("rate", 0) * 100 if vat_rate.get("rate") else 0
                            gross = vat_rate.get("gross", 0)
                            net = vat_rate.get("net", 0)
                            vat = vat_rate.get("vat", 0)
                            story.append(
                                Paragraph(
                                    f"{rate:.0f}%: Netto {net:.2f} €, MwSt {vat:.2f} €, Brutto {gross:.2f} €",
                                    sumup_info_style,
                                )
                            )

                story.append(Spacer(1, 5 * mm))

        # Footer
        story.append(
            HRFlowable(
                width="100%", thickness=0.5, lineCap="round", color=colors.HexColor("#cccccc")
            )
        )
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("Vielen Dank für Ihren Besuch!", footer_style))
        story.append(
            Paragraph("Diese Rechnung ist steuerrechtlich aufbewahrungspflichtig.", footer_style)
        )
        if restaurant.address:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph("Umsatzsteuer-ID gemäß §19 UStG", footer_style))

        # Speichere PDF
        doc.build(story)
        buffer.seek(0)

        return Response(
            content=buffer.getvalue(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="rechnung_{order.order_number or order.id}.pdf"'
            },
        )
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF-Bibliothek nicht installiert: {str(e)}",
        )
    except Exception as e:
        import traceback

        error_detail = f"Fehler beim Generieren der PDF: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_detail)
