"""SmartStock – Review Service"""
from __future__ import annotations
import math
from bson import ObjectId
from pymongo.database import Database
from ..models.review import build_review_document, REVIEW_STATUSES
from ..utils import utcnow, mongo_doc_to_dict


def create_review(db: Database, data: dict) -> dict:
    if not ObjectId.is_valid(str(data.get("product_id", ""))):
        raise ValueError("Invalid product_id.")
    product = db.products.find_one({"_id": ObjectId(data["product_id"])})
    if not product:
        raise ValueError("Product not found.")
    doc = build_review_document(data)
    result = db.reviews.insert_one(doc)
    doc["_id"] = result.inserted_id
    return mongo_doc_to_dict(doc)


def get_product_reviews(db: Database, product_id: str,
                        status: str = "approved",
                        page: int = 1, per_page: int = 10) -> dict:
    if not ObjectId.is_valid(product_id):
        return {"items": [], "pagination": {}}
    query = {"product_id": ObjectId(product_id)}
    if status:
        query["status"] = status
    total = db.reviews.count_documents(query)
    page = max(1, page)
    per_page = min(max(1, per_page), 50)
    skip = (page - 1) * per_page
    items = [
        mongo_doc_to_dict(d)
        for d in db.reviews.find(query).sort("review_date", -1).skip(skip).limit(per_page)
    ]
    return {
        "items": items,
        "pagination": {
            "total": total, "page": page, "per_page": per_page,
            "total_pages": math.ceil(total / per_page) if per_page else 1,
            "has_prev": page > 1,
            "has_next": page < math.ceil(total / per_page) if per_page else False,
        },
    }


def moderate_review(db: Database, review_id: str, status: str) -> bool:
    if not ObjectId.is_valid(review_id) or status not in REVIEW_STATUSES:
        return False
    result = db.reviews.update_one(
        {"_id": ObjectId(review_id)},
        {"$set": {"status": status, "updated_at": utcnow()}},
    )
    return result.modified_count > 0


def get_pending_reviews(db: Database, limit: int = 50) -> list[dict]:
    docs = db.reviews.find({"status": "pending"}).sort("created_at", 1).limit(limit)
    return [mongo_doc_to_dict(d) for d in docs]


def get_product_rating_summary(db: Database, product_id: str) -> dict:
    """Aggregation pipeline: average rating and distribution for one product."""
    if not ObjectId.is_valid(product_id):
        return {}
    pipeline = [
        {"$match": {"product_id": ObjectId(product_id), "status": "approved"}},
        {
            "$group": {
                "_id": "$product_id",
                "average_rating": {"$avg": "$rating"},
                "review_count": {"$sum": 1},
                "rating_1": {"$sum": {"$cond": [{"$eq": ["$rating", 1]}, 1, 0]}},
                "rating_2": {"$sum": {"$cond": [{"$eq": ["$rating", 2]}, 1, 0]}},
                "rating_3": {"$sum": {"$cond": [{"$eq": ["$rating", 3]}, 1, 0]}},
                "rating_4": {"$sum": {"$cond": [{"$eq": ["$rating", 4]}, 1, 0]}},
                "rating_5": {"$sum": {"$cond": [{"$eq": ["$rating", 5]}, 1, 0]}},
            }
        },
    ]
    result = list(db.reviews.aggregate(pipeline))
    if not result:
        return {"average_rating": None, "review_count": 0}
    r = result[0]
    return {
        "average_rating": round(r["average_rating"], 2),
        "review_count": r["review_count"],
        "distribution": {
            "1": r["rating_1"],
            "2": r["rating_2"],
            "3": r["rating_3"],
            "4": r["rating_4"],
            "5": r["rating_5"],
        },
    }
