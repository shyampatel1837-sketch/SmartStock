"""
SmartStock – Purchase Order Service

Key safety guarantee:
  Receiving stock uses a conditional update that checks the PO status
  is NOT already 'received' before marking it received and incrementing
  stock.  This prevents double-receipt even if a user retries the request.
"""
from __future__ import annotations
import math
from bson import ObjectId
from pymongo.database import Database
from ..models.purchase_order import build_po_document, PO_STATUSES
from ..models.stock_movement import build_movement
from ..utils import generate_po_reference, utcnow, mongo_doc_to_dict


def create_purchase_order(db: Database, data: dict) -> dict:
    reference = generate_po_reference(db)
    doc = build_po_document(data, reference)
    result = db.purchase_orders.insert_one(doc)
    doc["_id"] = result.inserted_id
    return mongo_doc_to_dict(doc)


def get_purchase_order(db: Database, po_id: str) -> dict | None:
    if not ObjectId.is_valid(po_id):
        return None
    doc = db.purchase_orders.find_one({"_id": ObjectId(po_id)})
    return mongo_doc_to_dict(doc) if doc else None


def list_purchase_orders(db: Database, supplier_id: str = None,
                         status: str = None, page: int = 1,
                         per_page: int = 20) -> dict:
    query: dict = {}
    if supplier_id and ObjectId.is_valid(supplier_id):
        query["supplier_id"] = ObjectId(supplier_id)
    if status:
        query["status"] = status
    total = db.purchase_orders.count_documents(query)
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    skip = (page - 1) * per_page
    items = [
        mongo_doc_to_dict(d)
        for d in db.purchase_orders.find(query)
        .sort("order_date", -1)
        .skip(skip)
        .limit(per_page)
    ]
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


def receive_purchase_order(db: Database, po_id: str, actor=None) -> dict:
    """
    Mark a PO as received and increase stock for each line item.

    Safety:
      - Conditional update on status != 'received' prevents double-receipt.
      - Uses update_one with $inc on product stock_qty atomically per product.
      - A stock_movement record is created for each line item.
    """
    if not ObjectId.is_valid(po_id):
        return {"success": False, "error": "Invalid PO ID."}
    oid = ObjectId(po_id)

    # Fetch PO
    po = db.purchase_orders.find_one({"_id": oid})
    if not po:
        return {"success": False, "error": "Purchase order not found."}
    if po["status"] in ("received", "cancelled"):
        return {
            "success": False,
            "error": f"Purchase order is already '{po['status']}'. Cannot receive again.",
        }

    now = utcnow()

    # Atomically mark as received only if still not received
    update_result = db.purchase_orders.update_one(
        {"_id": oid, "status": {"$nin": ["received", "cancelled"]}},
        {
            "$set": {
                "status": "received",
                "received_at": now,
                "received_by": actor,
                "updated_at": now,
            }
        },
    )

    if update_result.modified_count == 0:
        # Another request already received it
        return {
            "success": False,
            "error": "Purchase order was already received (concurrent update).",
        }

    # Increment stock and record movements
    movements = []
    for item in po.get("items", []):
        qty = int(item.get("quantity", 0))
        if qty <= 0:
            continue
        pid = item["product_id"]

        db.products.update_one(
            {"_id": pid},
            {
                "$inc": {"stock_qty": qty},
                "$set": {
                    # Update purchase cost to the latest received price
                    "purchase_cost": item["unit_price"],
                    "updated_at": now,
                },
            },
        )

        movement = build_movement(
            product_id=pid,
            movement_type="purchase_receipt",
            quantity_change=qty,
            reference_id=oid,
            reference_type="purchase_order",
            reason=f"Received PO {po['reference']}",
            actor=actor,
        )
        movements.append(movement)

    if movements:
        db.stock_movements.insert_many(movements)

    return {
        "success": True,
        "reference": po["reference"],
        "items_received": len(movements),
    }


def cancel_purchase_order(db: Database, po_id: str, reason: str = "") -> dict:
    if not ObjectId.is_valid(po_id):
        return {"success": False, "error": "Invalid PO ID."}
    oid = ObjectId(po_id)
    result = db.purchase_orders.update_one(
        {"_id": oid, "status": {"$nin": ["received", "cancelled"]}},
        {
            "$set": {
                "status": "cancelled",
                "notes": reason,
                "updated_at": utcnow(),
            }
        },
    )
    if result.modified_count == 0:
        return {"success": False, "error": "Cannot cancel this order."}
    return {"success": True}
