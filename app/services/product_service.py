"""
SmartStock – Product Service
"""
from __future__ import annotations
import math
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.database import Database
from ..models.product import build_product_document, update_fields, CATEGORIES
from ..utils import utcnow, mongo_doc_to_dict, safe_int


# ── Create ────────────────────────────────────────────────────────────────────

def create_product(db: Database, data: dict) -> dict:
    """Insert a new product. Raises ValueError on duplicate SKU."""
    sku = str(data["sku"]).strip().upper()
    if db.products.find_one({"sku": sku}):
        raise ValueError(f"A product with SKU '{sku}' already exists.")
    doc = build_product_document(data)
    result = db.products.insert_one(doc)
    doc["_id"] = result.inserted_id
    return mongo_doc_to_dict(doc)


# ── Read ──────────────────────────────────────────────────────────────────────

def get_product_by_id(db: Database, product_id: str) -> dict | None:
    if not ObjectId.is_valid(product_id):
        return None
    doc = db.products.find_one({"_id": ObjectId(product_id)})
    return mongo_doc_to_dict(doc) if doc else None


def get_product_by_sku(db: Database, sku: str) -> dict | None:
    doc = db.products.find_one({"sku": sku.strip().upper()})
    return mongo_doc_to_dict(doc) if doc else None


def list_products(db: Database, filters: dict, page: int = 1,
                  per_page: int = 20, sort_by: str = "name",
                  sort_dir: int = ASCENDING) -> dict:
    """
    Return paginated product list.

    Filters accepted:
      category, brand, status, min_price, max_price, low_stock (bool)

    Uses MongoDB query filters + projection; does NOT load entire collection.
    """
    query: dict = {}

    if filters.get("category"):
        query["category"] = filters["category"]
    if filters.get("brand"):
        query["brand"] = {"$regex": filters["brand"], "$options": "i"}
    if filters.get("status"):
        query["status"] = filters["status"]
    else:
        query["status"] = {"$ne": "discontinued"}

    # Price range filter uses compound category+price index
    price_filter: dict = {}
    if filters.get("min_price") is not None:
        from bson import Decimal128
        price_filter["$gte"] = Decimal128(str(filters["min_price"]))
    if filters.get("max_price") is not None:
        from bson import Decimal128
        price_filter["$lte"] = Decimal128(str(filters["max_price"]))
    if price_filter:
        query["selling_price"] = price_filter

    if filters.get("low_stock"):
        query["$expr"] = {"$lte": ["$stock_qty", "$reorder_threshold"]}

    valid_sort_fields = {
        "name": "name",
        "price": "selling_price",
        "stock": "stock_qty",
        "created": "created_at",
    }
    sort_field = valid_sort_fields.get(sort_by, "name")

    total = db.products.count_documents(query)
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    skip = (page - 1) * per_page

    cursor = (
        db.products
        .find(query)
        .sort(sort_field, sort_dir)
        .skip(skip)
        .limit(per_page)
    )
    items = [mongo_doc_to_dict(d) for d in cursor]

    return {
        "items": items,
        "pagination": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": math.ceil(total / per_page) if per_page else 1,
            "has_prev": page > 1,
            "has_next": page < math.ceil(total / per_page) if per_page else False,
        },
    }


def search_products(db: Database, query_text: str, limit: int = 20) -> list[dict]:
    """
    Full-text search using MongoDB $text index on name, description, brand.
    Falls back to regex on name if text index is unavailable.
    """
    query_text = query_text.strip()
    if not query_text:
        return []
    try:
        cursor = (
            db.products
            .find(
                {"$text": {"$search": query_text}, "status": {"$ne": "discontinued"}},
                {"score": {"$meta": "textScore"}},
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit)
        )
        return [mongo_doc_to_dict(d) for d in cursor]
    except Exception:
        # Fallback: regex search (does not use text index)
        cursor = (
            db.products
            .find({
                "$or": [
                    {"name": {"$regex": query_text, "$options": "i"}},
                    {"brand": {"$regex": query_text, "$options": "i"}},
                    {"sku": {"$regex": query_text, "$options": "i"}},
                ],
                "status": {"$ne": "discontinued"},
            })
            .limit(limit)
        )
        return [mongo_doc_to_dict(d) for d in cursor]


# ── Update ────────────────────────────────────────────────────────────────────

def update_product(db: Database, product_id: str, data: dict) -> dict | None:
    if not ObjectId.is_valid(product_id):
        return None
    oid = ObjectId(product_id)

    # Check SKU uniqueness if SKU is being changed
    if data.get("sku"):
        new_sku = str(data["sku"]).strip().upper()
        existing = db.products.find_one({"sku": new_sku, "_id": {"$ne": oid}})
        if existing:
            raise ValueError(f"SKU '{new_sku}' is already used by another product.")
        data["sku"] = new_sku

    fields = update_fields(data)
    db.products.update_one({"_id": oid}, {"$set": fields})
    return get_product_by_id(db, product_id)


def deactivate_product(db: Database, product_id: str) -> bool:
    if not ObjectId.is_valid(product_id):
        return False
    result = db.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"status": "inactive", "updated_at": utcnow()}},
    )
    return result.modified_count > 0


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_product(db: Database, product_id: str) -> dict:
    """
    Delete a product only if it has no sales history and no stock movements.
    Returns {'deleted': bool, 'reason': str}
    """
    if not ObjectId.is_valid(product_id):
        return {"deleted": False, "reason": "Invalid product ID."}
    oid = ObjectId(product_id)

    has_sales = db.sales.find_one({"items.product_id": oid})
    has_movements = db.stock_movements.find_one({"product_id": oid})

    if has_sales or has_movements:
        return {
            "deleted": False,
            "reason": (
                "Cannot delete: product has associated sales or stock movements. "
                "Set status to 'discontinued' instead."
            ),
        }
    db.products.delete_one({"_id": oid})
    return {"deleted": True, "reason": "Product deleted."}


# ── Low stock ─────────────────────────────────────────────────────────────────

def get_low_stock_products(db: Database, limit: int = 50) -> list[dict]:
    """Products at or below their reorder threshold (excluding discontinued)."""
    cursor = db.products.find(
        {
            "status": {"$ne": "discontinued"},
            "$expr": {"$lte": ["$stock_qty", "$reorder_threshold"]},
        }
    ).sort("stock_qty", ASCENDING).limit(limit)
    return [mongo_doc_to_dict(d) for d in cursor]
