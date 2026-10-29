"""
SmartStock – Product Validation
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from .base import require_fields, validate_positive_decimal, validate_quantity
from ..models.product import CATEGORIES, PRODUCT_STATUSES


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

    if data.get("category") and data["category"] not in CATEGORIES:
        errors.append("Select a valid product category.")
    if data.get("status") and data["status"] not in PRODUCT_STATUSES:
        errors.append("Select a valid product status.")
    if data.get("supplier_id"):
        from bson import ObjectId
        if not ObjectId.is_valid(str(data["supplier_id"])):
            errors.append("Select a valid supplier.")

    if "purchase_cost" in data:
        e = validate_positive_decimal(data["purchase_cost"], "Purchase cost", allow_zero=True)
        if e:
            errors.append(e)

    if "selling_price" in data:
        e = validate_positive_decimal(data["selling_price"], "Selling price", allow_zero=False)
        if e:
            errors.append(e)

    if "stock_qty" in data:
        e = validate_quantity(data["stock_qty"], "Stock quantity", min_val=0)
        if e:
            errors.append(e)

    if "reorder_threshold" in data:
        e = validate_quantity(data["reorder_threshold"], "Reorder threshold", min_val=0)
        if e:
            errors.append(e)

    if "warranty_months" in data and data["warranty_months"]:
        e = validate_quantity(data["warranty_months"], "Warranty months", min_val=0)
        if e:
            errors.append(e)

    return errors
