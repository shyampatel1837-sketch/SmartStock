"""
SmartStock – Review Model

Average ratings are NOT stored separately on the product document.
They are always calculated via aggregation pipelines so they can
never become stale or inconsistent with the underlying reviews.

Moderation statuses: pending → approved | rejected
"""
from bson import ObjectId
from ..utils import utcnow


REVIEW_STATUSES = ["pending", "approved", "rejected"]


def build_review_document(data: dict) -> dict:
    now = utcnow()
    rating = int(data.get("rating", 3))
    if rating < 1 or rating > 5:
        raise ValueError("Rating must be between 1 and 5")
    return {
        "product_id": ObjectId(data["product_id"]),
        "rating": rating,
        "title": str(data.get("title", "")).strip()[:200],
        "body": str(data.get("body", "")).strip()[:2000],
        "reviewer_name": str(data.get("reviewer_name", "Anonymous")).strip()[:100],
        # Sale reference for verified-purchase logic (optional)
        "sale_id": (
            ObjectId(data["sale_id"])
            if data.get("sale_id") and ObjectId.is_valid(str(data["sale_id"]))
            else None
        ),
        "status": "pending",
        "review_date": now,
        "created_at": now,
        "updated_at": now,
    }
