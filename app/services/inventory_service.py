"""
SmartStock – Inventory / Stock Adjustment Service
"""
from __future__ import annotations
import math
import logging
from bson import ObjectId
from pymongo.database import Database
from ..models.stock_movement import build_movement, MOVEMENT_TYPES
from ..utils import utcnow, mongo_doc_to_dict

logger = logging.getLogger(__name__)


def adjust_stock(db: Database, product_id: str, quantity_change: int,
                 reason: str, movement_type: str = "adjustment_up",
                 actor=None, notes: str = "") -> dict:
    """
    Manually adjust stock for a product.
    A corresponding stock_movement record is always created.
    Prevents negative stock unless explicitly configured.
    """
    if isinstance(quantity_change, bool) or not isinstance(quantity_change, int):
        return {"success": False, "error": "Quantity change must be a whole number."}
    if not ObjectId.is_valid(product_id):
        return {"success": False, "error": "Invalid product ID."}
    oid = ObjectId(product_id)

    product = db.products.find_one({"_id": oid}, {"stock_qty": 1, "name": 1})
    if not product:
        return {"success": False, "error": "Product not found."}

    reason = str(reason or "").strip()
    if not reason:
        return {"success": False, "error": "A reason is required for stock adjustments."}
    if not quantity_change:
        return {"success": False, "error": "Stock adjustment cannot be zero."}

    current_qty = int(product.get("stock_qty", 0))
    new_qty = current_qty + quantity_change

    if new_qty < 0:
        return {
            "success": False,
            "error": (
                f"Adjustment would result in negative stock "
                f"({current_qty} + ({quantity_change}) = {new_qty}). "
                "Set a higher quantity or record a damage/loss reason."
            ),
        }

    movement_type = (
        "adjustment_up" if quantity_change >= 0 else "adjustment_down"
    )

    update_result = db.products.update_one(
        {"_id": oid, "stock_qty": {"$gte": max(0, -quantity_change)}},
        {"$inc": {"stock_qty": quantity_change}, "$set": {"updated_at": utcnow()}},
    )
    if update_result.modified_count != 1:
        return {
            "success": False,
            "error": "Stock changed during this adjustment or is insufficient; reload and try again.",
        }
    movement = build_movement(
        product_id=oid,
        movement_type=movement_type,
        quantity_change=quantity_change,
        reason=reason,
        actor=actor,
        notes=notes,
    )
    try:
        db.stock_movements.insert_one(movement)
    except Exception as exc:
        try:
            rollback = db.products.update_one(
                {"_id": oid},
                {"$inc": {"stock_qty": -quantity_change}},
            )
            if rollback.modified_count != 1:
                raise RuntimeError("Product stock could not be restored.")
        except Exception as rollback_exc:
            logger.exception("Stock adjustment rollback failed for product %s", oid)
            raise RuntimeError(
                "Stock movement was not recorded and stock rollback failed; "
                "reconcile this product."
            ) from rollback_exc
        raise RuntimeError(
            "Stock movement could not be recorded; the stock adjustment was rolled back."
        ) from exc
    latest = db.products.find_one({"_id": oid}, {"stock_qty": 1})
    return {"success": True, "new_stock_qty": latest["stock_qty"] if latest else new_qty}


def record_damage(db: Database, product_id: str, quantity: int,
                  reason: str, actor=None) -> dict:
    """Write off damaged/defective items."""
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        return {"success": False, "error": "Quantity must be a whole number."}
    if quantity <= 0:
        return {"success": False, "error": "Quantity must be positive."}
    reason = str(reason or "").strip()
    if not ObjectId.is_valid(product_id):
        return {"success": False, "error": "Invalid product ID."}
    oid = ObjectId(product_id)
    product = db.products.find_one({"_id": oid}, {"stock_qty": 1})
    if not product:
        return {"success": False, "error": "Product not found."}
    if not reason:
        return {"success": False, "error": "A reason is required to record damage."}
    if product["stock_qty"] < quantity:
        return {"success": False, "error": "Insufficient stock to record this damage."}

    update_result = db.products.update_one(
        {"_id": oid, "stock_qty": {"$gte": quantity}},
        {"$inc": {"stock_qty": -quantity}, "$set": {"updated_at": utcnow()}},
    )
    if update_result.modified_count != 1:
        return {"success": False, "error": "Stock changed during this write-off; reload and try again."}
    movement = build_movement(
        product_id=oid,
        movement_type="damage",
        quantity_change=-quantity,
        reason=reason,
        actor=actor,
    )
    try:
        db.stock_movements.insert_one(movement)
    except Exception as exc:
        try:
            rollback = db.products.update_one(
                {"_id": oid}, {"$inc": {"stock_qty": quantity}}
            )
            if rollback.modified_count != 1:
                raise RuntimeError("Product stock could not be restored.")
        except Exception as rollback_exc:
            logger.exception("Damage write-off rollback failed for product %s", oid)
            raise RuntimeError(
                "Damage movement was not recorded and stock rollback failed; "
                "reconcile this product."
            ) from rollback_exc
        raise RuntimeError(
            "Damage movement could not be recorded; the stock write-off was rolled back."
        ) from exc
    return {"success": True}


def get_stock_movements(db: Database, product_id: str = None,
                        movement_type: str = None, page: int = 1,
                        per_page: int = 30) -> dict:
    query: dict = {}
    if product_id and ObjectId.is_valid(product_id):
        query["product_id"] = ObjectId(product_id)
    if movement_type and movement_type in MOVEMENT_TYPES:
        query["movement_type"] = movement_type

    total = db.stock_movements.count_documents(query)
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    skip = (page - 1) * per_page
    items = [
        mongo_doc_to_dict(d)
        for d in db.stock_movements.find(query)
        .sort("created_at", -1)
        .skip(skip)
        .limit(per_page)
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
