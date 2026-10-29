"""SmartStock – Sale Validation"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from bson import ObjectId
from .base import require_fields, validate_positive_decimal, validate_quantity


def validate_sale(data: dict) -> list[str]:
    errors: list[str] = []
    errors += require_fields(data, ["items", "payment_method"])

    items = data.get("items", [])
    subtotal = Decimal("0")
    if not isinstance(items, list) or not items:
        errors.append("A sale must have at least one item.")
    else:
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict):
                errors.append(f"Item {i} must be an object.")
                continue
            errors += require_fields(item, ["product_id", "quantity", "unit_price"])
            product_id = item.get("product_id")
            if product_id and not ObjectId.is_valid(str(product_id)):
                errors.append(f"Item {i} has an invalid product.")
            e = validate_quantity(item.get("quantity"), f"Item {i} quantity")
            if e:
                errors.append(e)
            e = validate_positive_decimal(item.get("unit_price"), f"Item {i} price")
            if e:
                errors.append(e)
            discount_error = validate_positive_decimal(
                item.get("discount_amount", 0), f"Item {i} discount", allow_zero=True
            )
            if discount_error:
                errors.append(discount_error)

            try:
                quantity = int(item.get("quantity"))
                unit_price = Decimal(str(item.get("unit_price")))
                item_discount = Decimal(str(item.get("discount_amount", 0)))
                if (
                    quantity > 0
                    and unit_price.is_finite()
                    and item_discount.is_finite()
                    and unit_price > 0
                    and item_discount >= 0
                ):
                    line_total = quantity * unit_price - item_discount
                    if line_total < 0:
                        errors.append(f"Item {i} discount cannot exceed its value.")
                    else:
                        subtotal += line_total
            except (InvalidOperation, TypeError, ValueError):
                continue

    from ..models.sale import PAYMENT_METHODS
    if data.get("payment_method") and data["payment_method"] not in PAYMENT_METHODS:
        errors.append(f"Invalid payment method. Choose from: {', '.join(PAYMENT_METHODS)}")

    if data.get("discount_amount"):
        e = validate_positive_decimal(data["discount_amount"],
                                      "Discount", allow_zero=True)
        if e:
            errors.append(e)
        else:
            try:
                if Decimal(str(data["discount_amount"])) > subtotal:
                    errors.append("Discount cannot exceed the sale subtotal.")
            except (InvalidOperation, TypeError, ValueError):
                pass

    idem_key = data.get("idempotency_key")
    if idem_key is not None and (
        not isinstance(idem_key, str) or not 1 <= len(idem_key) <= 128
    ):
        errors.append("Idempotency key must be a string of 1 to 128 characters.")

    return errors
