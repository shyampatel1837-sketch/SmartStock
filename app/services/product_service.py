"""
SmartStock – Product Service
"""
from __future__ import annotations
import math
import re
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, OperationFailure
from ..models.product import (
    SPECIFICATION_FIELDS,
    build_product_document,
    update_fields,
    CATEGORIES,
)
from ..models.stock_movement import build_movement
from ..utils import utcnow, mongo_doc_to_dict, safe_int
from ..validators.product_validator import validate_product


# ── Create ────────────────────────────────────────────────────────────────────

def create_product(db: Database, data: dict) -> dict:
    """Insert a new product. Raises ValueError on duplicate SKU."""
    errors = validate_product(data)
    if errors:
        raise ValueError(" ".join(errors))
    sku = str(data["sku"]).strip().upper()
    if db.products.find_one({"sku": sku}):
        raise ValueError(f"A product with SKU '{sku}' already exists.")
    doc = build_product_document(data)
    try:
        result = db.products.insert_one(doc)
    except DuplicateKeyError as exc:
        raise ValueError(f"A product with SKU '{sku}' already exists.") from exc
    doc["_id"] = result.inserted_id
    if doc["stock_qty"] > 0:
        try:
            db.stock_movements.insert_one(
                build_movement(
                    product_id=result.inserted_id,
                    movement_type="opening_stock",
                    quantity_change=doc["stock_qty"],
                    reference_id=result.inserted_id,
                    reference_type="product",
                    reason="Opening stock at product creation",
                )
            )
        except Exception as exc:
            try:
                db.products.delete_one({"_id": result.inserted_id})
            except Exception as cleanup_exc:
                raise RuntimeError(
                    "Opening stock could not be recorded and the product "
                    "could not be rolled back; reconcile product stock."
                ) from cleanup_exc
            raise RuntimeError(
                "Product creation was rolled back because opening stock "
                "could not be recorded."
            ) from exc
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
        query["brand"] = {"$regex": re.escape(str(filters["brand"])[:100]), "$options": "i"}
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
                {"$text": {"$search": query_text}, "status": "active"},
                {"score": {"$meta": "textScore"}},
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit)
        )
        return [mongo_doc_to_dict(d) for d in cursor]
    except OperationFailure as exc:
        if exc.code != 27:
            raise
        # Fallback: regex search (does not use text index)
        escaped_query = re.escape(query_text)
        cursor = (
            db.products
            .find({
                "$or": [
                    {"name": {"$regex": escaped_query, "$options": "i"}},
                    {"brand": {"$regex": escaped_query, "$options": "i"}},
                    {"sku": {"$regex": escaped_query, "$options": "i"}},
                ],
                "status": "active",
            })
            .limit(limit)
        )
        return [mongo_doc_to_dict(d) for d in cursor]


# ── Update ────────────────────────────────────────────────────────────────────

def update_product(db: Database, product_id: str, data: dict) -> dict | None:
    if not ObjectId.is_valid(product_id):
        return None
    errors = validate_product(data, is_update=True)
    if errors:
        raise ValueError(" ".join(errors))
    oid = ObjectId(product_id)
    current_product = db.products.find_one({"_id": oid}, {"category": 1})
    if not current_product:
        return None
    category_changed = (
        "category" in data and data["category"] != current_product.get("category")
    )

    # Check SKU uniqueness if SKU is being changed
    if data.get("sku"):
        new_sku = str(data["sku"]).strip().upper()
        existing = db.products.find_one({"sku": new_sku, "_id": {"$ne": oid}})
        if existing:
            raise ValueError(f"SKU '{new_sku}' is already used by another product.")
        data["sku"] = new_sku

    fields = update_fields(data)
    update = {"$set": fields}
    if category_changed:
        kept_specs = {
            field
            for field in SPECIFICATION_FIELDS
            if f"specs.{field}" in fields
        }
        cleared_specs = {
            f"specs.{field}": ""
            for field in SPECIFICATION_FIELDS
            if field not in kept_specs
        }
    else:
        cleared_specs = {
            f"specs.{field}": ""
            for field in SPECIFICATION_FIELDS
            if field in data and data[field] in (None, "", "0")
        }
    if cleared_specs:
        update["$unset"] = cleared_specs
    db.products.update_one({"_id": oid}, update)
    return get_product_by_id(db, product_id)


def deactivate_product(db: Database, product_id: str) -> bool:
    if not ObjectId.is_valid(product_id):
        return False
    result = db.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"status": "inactive", "updated_at": utcnow()}},
    )
    return result.matched_count > 0 and result.modified_count > 0


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
    has_purchase_orders = db.purchase_orders.find_one({"items.product_id": oid})

    if has_sales or has_movements or has_purchase_orders:
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
            "status": "active",
            "$expr": {"$lte": ["$stock_qty", "$reorder_threshold"]},
        }
    ).sort("stock_qty", ASCENDING).limit(limit)
    return [mongo_doc_to_dict(d) for d in cursor]
