"""Tax calculation service for German VAT (7%/19%) with discount distribution."""
from __future__ import annotations


def calculate_totals(
    items: list[dict],
    discount_amount: float = 0.0,
    discount_percentage: float | None = None,
    tip_amount: float = 0.0,
) -> dict[str, float]:
    """
    Calculate order totals from items with German tax split.

    All prices are inclusive of VAT. VAT extraction: price * (rate / (1 + rate))
    Discount is distributed proportionally across tax categories.

    Args:
        items: List of dicts with total_price and tax_rate.
        discount_amount: Fixed discount in EUR.
        discount_percentage: Percentage discount (0-100). Takes precedence over discount_amount.
        tip_amount: Tip in EUR.

    Returns:
        Dict with subtotal, tax_amount_7, tax_amount_19, tax_amount, discount_amount, tip_amount, total.
    """
    subtotal = sum(item.get("total_price", 0.0) for item in items)

    if discount_percentage is not None and discount_percentage > 0:
        effective_discount = round(subtotal * discount_percentage / 100, 2)
    else:
        effective_discount = min(discount_amount, subtotal)

    # Proportional VAT calculation
    sum_7 = 0.0
    sum_19 = 0.0
    for item in items:
        tp = item.get("total_price", 0.0)
        rate = item.get("tax_rate", 0.19)
        vat = tp * (rate / (1 + rate))
        if abs(rate - 0.07) < 0.001:
            sum_7 += vat
        else:
            sum_19 += vat

    # Apply discount proportionally to VAT
    total_vat = sum_7 + sum_19
    if subtotal > 0 and effective_discount > 0:
        ratio = effective_discount / subtotal
        sum_7 -= sum_7 * ratio
        sum_19 -= sum_19 * ratio

    tax_amount_7 = round(max(sum_7, 0.0), 2)
    tax_amount_19 = round(max(sum_19, 0.0), 2)
    tax_amount = round(tax_amount_7 + tax_amount_19, 2)
    total = round(subtotal - effective_discount + tip_amount, 2)

    return {
        "subtotal": round(subtotal, 2),
        "tax_amount_7": tax_amount_7,
        "tax_amount_19": tax_amount_19,
        "tax_amount": tax_amount,
        "discount_amount": round(effective_discount, 2),
        "tip_amount": round(tip_amount, 2),
        "total": total,
    }
