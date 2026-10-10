"""SmartStock – Sale Validation"""
from __future__ import annotations
from .base import require_fields, validate_positive_decimal, validate_quantity


def validate_sale(data: dict) -> list[str]:
    errors: list[str] = []
    errors += require_fields(data, ["items", "payment_method"])

    items = data.get("items", [])
    if not items:
        errors.append("A sale must have at least one item.")
    else:
        for i, item in enumerate(items, 1):
            errors += require_fields(item, ["product_id", "quantity", "unit_price"])
            e = validate_quantity(item.get("quantity"), f"Item {i} quantity")
            if e:
                errors.append(e)
            e = validate_positive_decimal(item.get("unit_price"), f"Item {i} price")
            if e:
                errors.append(e)

    from ..models.sale import PAYMENT_METHODS
    if data.get("payment_method") and data["payment_method"] not in PAYMENT_METHODS:
        errors.append(f"Invalid payment method. Choose from: {', '.join(PAYMENT_METHODS)}")

    if data.get("discount_amount"):
        e = validate_positive_decimal(data["discount_amount"],
                                      "Discount", allow_zero=True)
        if e:
            errors.append(e)

    return errors
