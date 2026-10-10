"""
SmartStock – Product Validation
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from .base import ValidationError, require_fields, validate_positive_decimal


def validate_product(data: dict, is_update: bool = False) -> list[str]:
    """
    Validate product form data.
    Returns a list of error strings (empty list = valid).
    """
    errors: list[str] = []

    if not is_update:
        errors += require_fields(data, ["sku", "name", "category",
                                        "purchase_cost", "selling_price"])

    if data.get("sku"):
        sku = str(data["sku"]).strip()
        if len(sku) < 2 or len(sku) > 50:
            errors.append("SKU must be between 2 and 50 characters.")
        import re
        if not re.match(r'^[A-Za-z0-9_\-]+$', sku):
            errors.append("SKU may only contain letters, digits, hyphens, and underscores.")

    if data.get("name") and len(str(data["name"]).strip()) < 2:
        errors.append("Product name must be at least 2 characters.")

    if "purchase_cost" in data:
        e = validate_positive_decimal(data["purchase_cost"], "Purchase cost", allow_zero=True)
        if e:
            errors.append(e)

    if "selling_price" in data:
        e = validate_positive_decimal(data["selling_price"], "Selling price", allow_zero=False)
        if e:
            errors.append(e)

    if "stock_qty" in data:
        try:
            q = int(data["stock_qty"])
            if q < 0:
                errors.append("Stock quantity cannot be negative.")
        except (TypeError, ValueError):
            errors.append("Stock quantity must be a whole number.")

    if "reorder_threshold" in data:
        try:
            r = int(data["reorder_threshold"])
            if r < 0:
                errors.append("Reorder threshold cannot be negative.")
        except (TypeError, ValueError):
            errors.append("Reorder threshold must be a whole number.")

    if "warranty_months" in data and data["warranty_months"]:
        try:
            w = int(data["warranty_months"])
            if w < 0:
                errors.append("Warranty months cannot be negative.")
        except (TypeError, ValueError):
            errors.append("Warranty months must be a whole number.")

    return errors
