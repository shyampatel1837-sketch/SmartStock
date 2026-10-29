"""Validation for supplier purchase orders."""
from decimal import Decimal, InvalidOperation

from bson import ObjectId

from .base import require_fields, validate_positive_decimal, validate_quantity
from ..utils import parse_date


def validate_purchase_order(data: dict) -> list[str]:
    errors = require_fields(data, ["supplier_id", "items"])
    supplier_id = data.get("supplier_id")
    if supplier_id and not ObjectId.is_valid(str(supplier_id)):
        errors.append("Select a valid supplier.")
    for field in ("order_date", "expected_date"):
        date_value = data.get(field)
        if date_value and not parse_date(str(date_value)):
            errors.append(f"{field.replace('_', ' ').title()} must be a valid date.")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        errors.append("A purchase order must have at least one item.")
        return errors

    subtotal = Decimal("0")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"Item {index} must be an object.")
            continue
        errors.extend(
            require_fields(item, ["product_id", "quantity", "unit_price"])
        )
        product_id = item.get("product_id")
        if product_id and not ObjectId.is_valid(str(product_id)):
            errors.append(f"Item {index} has an invalid product.")

        quantity_error = validate_quantity(
            item.get("quantity"), f"Item {index} quantity"
        )
        if quantity_error:
            errors.append(quantity_error)
        price_error = validate_positive_decimal(
            item.get("unit_price"), f"Item {index} unit price", allow_zero=True
        )
        if price_error:
            errors.append(price_error)

        try:
            quantity = int(item.get("quantity"))
            price = Decimal(str(item.get("unit_price")))
            if quantity > 0 and price.is_finite() and price >= 0:
                subtotal += quantity * price
        except (InvalidOperation, TypeError, ValueError):
            continue

    for field in ("discount_amount", "tax_amount"):
        error = validate_positive_decimal(
            data.get(field, 0), field.replace("_", " ").title(), allow_zero=True
        )
        if error:
            errors.append(error)

    try:
        discount = Decimal(str(data.get("discount_amount", 0)))
        if discount.is_finite() and discount > subtotal:
            errors.append("Discount cannot exceed the purchase subtotal.")
    except (InvalidOperation, TypeError, ValueError):
        pass

    return errors
