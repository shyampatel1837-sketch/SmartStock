"""Validation for customer product reviews."""
from bson import ObjectId

from .base import require_fields, validate_quantity


def validate_review(data: dict) -> list[str]:
    errors = require_fields(data, ["product_id", "rating", "reviewer_name", "body"])
    product_id = data.get("product_id")
    if product_id and not ObjectId.is_valid(str(product_id)):
        errors.append("Select a valid product.")

    rating_error = validate_quantity(data.get("rating"), "Rating", min_val=1)
    if rating_error:
        errors.append(rating_error)
    else:
        try:
            if int(data["rating"]) > 5:
                errors.append("Rating must be between 1 and 5.")
        except (TypeError, ValueError):
            errors.append("Rating must be a whole number.")

    reviewer_name = str(data.get("reviewer_name", "")).strip()
    if not reviewer_name or len(reviewer_name) > 100:
        errors.append("Reviewer name is required and cannot exceed 100 characters.")
    if len(str(data.get("title", ""))) > 200:
        errors.append("Review title cannot exceed 200 characters.")
    if len(str(data.get("body", ""))) > 2000:
        errors.append("Review cannot exceed 2000 characters.")

    sale_id = data.get("sale_id")
    if sale_id and not ObjectId.is_valid(str(sale_id)):
        errors.append("Sale reference is invalid.")
    return errors
