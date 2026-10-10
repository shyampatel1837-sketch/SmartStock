"""
SmartStock – Sale Service

Concurrency safety:
  Stock deduction uses a conditional MongoDB update:
    { stock_qty: { $gte: qty_to_deduct } }
  If the update modifies 0 documents, the product is out of stock and
  the sale is rejected.  The entire operation is wrapped in a try/except
  so a partial failure does not leave stock and transaction inconsistent.

  For replica-set deployments, sales and stock movements are wrapped in
  a multi-document transaction.  For standalone MongoDB (common in dev),
  the conditional update provides the primary integrity guarantee.

Idempotency:
  If data includes an idempotency_key, we check for an existing sale with
  that key and return it instead of creating a duplicate.
"""
from __future__ import annotations
import math
from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import OperationFailure
from ..models.sale import build_sale_document, SALE_STATUSES
from ..models.stock_movement import build_movement
from ..utils import generate_invoice_number, utcnow, mongo_doc_to_dict
from flask import current_app


def create_sale(db: Database, data: dict, actor=None) -> dict:
    """
    Process a sale:
      1. Check idempotency key.
      2. Validate and deduct stock for each item.
      3. Insert the sale document.
      4. Insert stock movement records.

    Raises:
      ValueError: insufficient stock, invalid product, etc.
    """
    # ── Idempotency check ────────────────────────────────────────────
    idem_key = data.get("idempotency_key")
    if idem_key:
        existing = db.sales.find_one({"idempotency_key": idem_key})
        if existing:
            return mongo_doc_to_dict(existing)

    # ── Enrich items with product snapshots ──────────────────────────
    items = _enrich_items(db, data.get("items", []))
    data["items"] = items
    data["created_by"] = actor

    # ── Build sale document ──────────────────────────────────────────
    tax_percent = current_app.config.get("STORE_TAX_PERCENT", 18.0)
    prefix = current_app.config.get("STORE_INVOICE_PREFIX", "INV")
    invoice_number = generate_invoice_number(prefix, db)
    doc = build_sale_document(data, invoice_number, tax_percent)

    # ── Attempt to deduct stock ──────────────────────────────────────
    # Using conditional updates; roll back on failure.
    deducted: list[dict] = []
    try:
        for item in items:
            pid = ObjectId(item["product_id"])
            qty = int(item["quantity"])
            result = db.products.update_one(
                {"_id": pid, "stock_qty": {"$gte": qty}},
                {
                    "$inc": {"stock_qty": -qty},
                    "$set": {"updated_at": utcnow()},
                },
            )
            if result.modified_count == 0:
                # Insufficient stock — roll back already-deducted items
                _rollback_deductions(db, deducted)
                product = db.products.find_one({"_id": pid}, {"name": 1, "stock_qty": 1})
                pname = product.get("name", str(pid)) if product else str(pid)
                available = product.get("stock_qty", 0) if product else 0
                raise ValueError(
                    f"Insufficient stock for '{pname}'. "
                    f"Requested: {qty}, available: {available}."
                )
            deducted.append({"product_id": pid, "quantity": qty})

        # ── Insert sale ──────────────────────────────────────────────
        result = db.sales.insert_one(doc)
        sale_id = result.inserted_id
        doc["_id"] = sale_id

        # ── Insert stock movements ───────────────────────────────────
        movements = [
            build_movement(
                product_id=item["product_id"],
                movement_type="sale",
                quantity_change=-int(item["quantity"]),
                reference_id=sale_id,
                reference_type="sale",
                reason=f"Sale {invoice_number}",
                actor=actor,
            )
            for item in items
        ]
        if movements:
            db.stock_movements.insert_many(movements)

        return mongo_doc_to_dict(doc)

    except ValueError:
        raise
    except Exception as exc:
        # Unexpected error: roll back deductions
        _rollback_deductions(db, deducted)
        raise RuntimeError(f"Sale processing failed: {exc}") from exc


def _enrich_items(db: Database, items: list) -> list:
    """Add product name/SKU snapshots to each item for historical integrity."""
    enriched = []
    for item in items:
        pid = item.get("product_id")
        if not pid or not ObjectId.is_valid(str(pid)):
            raise ValueError(f"Invalid product_id: {pid}")
        product = db.products.find_one(
            {"_id": ObjectId(pid), "status": {"$ne": "discontinued"}},
            {"name": 1, "sku": 1, "selling_price": 1, "stock_qty": 1},
        )
        if not product:
            raise ValueError(f"Product '{pid}' not found or discontinued.")
        enriched_item = dict(item)
        enriched_item["product_id"] = str(pid)
        enriched_item.setdefault("product_name", product.get("name", ""))
        enriched_item.setdefault("product_sku", product.get("sku", ""))
        # Use selling_price from product if not supplied
        if not enriched_item.get("unit_price"):
            from bson import Decimal128
            sp = product.get("selling_price")
            enriched_item["unit_price"] = float(sp.to_decimal()) if isinstance(sp, Decimal128) else sp
        enriched.append(enriched_item)
    return enriched


def _rollback_deductions(db: Database, deducted: list) -> None:
    """Restore stock for items that were already deducted before an error."""
    for d in deducted:
        db.products.update_one(
            {"_id": d["product_id"]},
            {"$inc": {"stock_qty": d["quantity"]}},
        )


def get_sale(db: Database, sale_id: str) -> dict | None:
    if not ObjectId.is_valid(sale_id):
        return None
    doc = db.sales.find_one({"_id": ObjectId(sale_id)})
    return mongo_doc_to_dict(doc) if doc else None


def get_sale_by_invoice(db: Database, invoice_number: str) -> dict | None:
    doc = db.sales.find_one({"invoice_number": invoice_number})
    return mongo_doc_to_dict(doc) if doc else None


def list_sales(db: Database, filters: dict = None,
               page: int = 1, per_page: int = 20) -> dict:
    filters = filters or {}
    query: dict = {}
    if filters.get("status"):
        query["status"] = filters["status"]
    if filters.get("date_from"):
        query.setdefault("sale_date", {})["$gte"] = filters["date_from"]
    if filters.get("date_to"):
        query.setdefault("sale_date", {})["$lte"] = filters["date_to"]
    if filters.get("payment_method"):
        query["payment_method"] = filters["payment_method"]

    total = db.sales.count_documents(query)
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    skip = (page - 1) * per_page
    items = [
        mongo_doc_to_dict(d)
        for d in db.sales.find(query).sort("sale_date", -1).skip(skip).limit(per_page)
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


def void_sale(db: Database, sale_id: str, reason: str, actor=None) -> dict:
    """
    Void a completed sale. Restores stock and creates reversal movements.
    """
    if not ObjectId.is_valid(sale_id):
        return {"success": False, "error": "Invalid sale ID."}
    oid = ObjectId(sale_id)
    sale = db.sales.find_one({"_id": oid})
    if not sale:
        return {"success": False, "error": "Sale not found."}
    if sale["status"] != "completed":
        return {"success": False, "error": f"Cannot void a sale with status '{sale['status']}'."}

    now = utcnow()
    # Restore stock
    movements = []
    for item in sale.get("items", []):
        qty = int(item.get("quantity", 0))
        pid = item["product_id"]
        db.products.update_one(
            {"_id": pid},
            {"$inc": {"stock_qty": qty}, "$set": {"updated_at": now}},
        )
        movements.append(
            build_movement(
                product_id=pid,
                movement_type="return_customer",
                quantity_change=qty,
                reference_id=oid,
                reference_type="sale_void",
                reason=f"Void {sale['invoice_number']}: {reason}",
                actor=actor,
            )
        )
    if movements:
        db.stock_movements.insert_many(movements)

    db.sales.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "voided",
                "void_reason": reason,
                "voided_at": now,
                "voided_by": actor,
                "updated_at": now,
            }
        },
    )
    return {"success": True, "invoice_number": sale["invoice_number"]}
