"""
SmartStock – Sale Service

Concurrency safety:
  Stock deduction uses a conditional MongoDB update:
    { stock_qty: { $gte: qty_to_deduct } }
  If the update modifies 0 documents, the product is out of stock and
  the sale is rejected. Multi-document writes use compensating updates
  when an application error occurs; they are not MongoDB transactions.
  A process failure during the operation can still require reconciliation.

Idempotency:
  If data includes an idempotency_key, we check for an existing sale with
  that key and return it instead of creating a duplicate.
"""
from __future__ import annotations
import math
import logging
from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from ..models.sale import build_sale_document, SALE_STATUSES
from ..models.stock_movement import build_movement
from ..utils import generate_invoice_number, utcnow, mongo_doc_to_dict
from ..validators.sale_validator import validate_sale
from flask import current_app

logger = logging.getLogger(__name__)


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
    data = dict(data)
    idem_key = data.get("idempotency_key")
    if idem_key:
        existing = db.sales.find_one({
            "idempotency_key": idem_key,
            "created_by": actor,
        })
        if existing:
            return mongo_doc_to_dict(existing)

    errors = validate_sale(data)
    if errors:
        raise ValueError(" ".join(errors))

    # ── Enrich items with product snapshots ──────────────────────────
    items = _enrich_items(db, data.get("items", []))
    data["items"] = items
    enriched_errors = validate_sale(data)
    if enriched_errors:
        raise ValueError(" ".join(enriched_errors))
    data["created_by"] = actor

    # ── Build sale document ──────────────────────────────────────────
    tax_percent = current_app.config.get("STORE_TAX_PERCENT", 18.0)
    prefix = current_app.config.get("STORE_INVOICE_PREFIX", "INV")
    invoice_number = generate_invoice_number(prefix, db)
    doc = build_sale_document(data, invoice_number, tax_percent)

    # ── Attempt to deduct stock ──────────────────────────────────────
    # Using conditional updates; roll back on failure.
    deducted: list[dict] = []
    sale_id = None
    try:
        for item in items:
            pid = ObjectId(item["product_id"])
            qty = int(item["quantity"])
            result = db.products.update_one(
                {"_id": pid, "status": "active", "stock_qty": {"$gte": qty}},
                {
                    "$inc": {"stock_qty": -qty},
                    "$set": {"updated_at": utcnow()},
                },
            )
            if result.modified_count == 0:
                product = db.products.find_one({"_id": pid}, {"name": 1, "stock_qty": 1})
                pname = product.get("name", str(pid)) if product else str(pid)
                available = product.get("stock_qty", 0) if product else 0
                raise ValueError(
                    f"Product '{pname}' is unavailable or has insufficient stock. "
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
        if sale_id is not None:
            _compensate_sale(db, sale_id, deducted)
        else:
            try:
                _rollback_deductions(db, deducted)
            except Exception as rollback_exc:
                logger.exception("Sale inventory rollback failed")
                raise RuntimeError(
                    "Sale failed and inventory rollback was incomplete; "
                    "reconcile the sale and stock movements."
                ) from rollback_exc
        raise
    except DuplicateKeyError as exc:
        if sale_id is None and idem_key:
            existing = db.sales.find_one({
                "idempotency_key": idem_key,
                "created_by": actor,
            })
            if existing:
                _rollback_deductions(db, deducted)
                return mongo_doc_to_dict(existing)
        _compensate_sale(db, sale_id, deducted)
        raise RuntimeError(f"Sale processing failed: {exc}") from exc
    except Exception as exc:
        _compensate_sale(db, sale_id, deducted)
        raise RuntimeError(f"Sale processing failed: {exc}") from exc


def _enrich_items(db: Database, items: list) -> list:
    """Add product name/SKU snapshots to each item for historical integrity."""
    enriched = []
    for item in items:
        pid = item.get("product_id")
        if not pid or not ObjectId.is_valid(str(pid)):
            raise ValueError(f"Invalid product_id: {pid}")
        product = db.products.find_one(
            {"_id": ObjectId(pid), "status": "active"},
            {"name": 1, "sku": 1, "selling_price": 1, "stock_qty": 1},
        )
        if not product:
            raise ValueError(f"Product '{pid}' not found or discontinued.")
        enriched_item = dict(item)
        enriched_item["product_id"] = str(pid)
        enriched_item.setdefault("product_name", product.get("name", ""))
        enriched_item.setdefault("product_sku", product.get("sku", ""))
        # Prices are always taken from the catalogue, never trusted from the client.
        from bson import Decimal128
        selling_price = product.get("selling_price")
        enriched_item["unit_price"] = (
            str(selling_price.to_decimal())
            if isinstance(selling_price, Decimal128)
            else str(selling_price)
        )
        enriched.append(enriched_item)
    return enriched


def _rollback_deductions(db: Database, deducted: list) -> None:
    """Restore stock for items that were already deducted before an error."""
    for d in deducted:
        result = db.products.update_one(
            {"_id": d["product_id"]},
            {"$inc": {"stock_qty": d["quantity"]}},
        )
        if result.modified_count != 1:
            raise RuntimeError(
                f"Could not restore stock for product {d['product_id']}."
            )


def _compensate_sale(db: Database, sale_id, deducted: list) -> None:
    errors = []
    if sale_id is not None:
        try:
            db.stock_movements.delete_many({"reference_id": sale_id, "reference_type": "sale"})
        except Exception as exc:
            errors.append(str(exc))
        try:
            db.sales.delete_one({"_id": sale_id})
        except Exception as exc:
            errors.append(str(exc))
    try:
        _rollback_deductions(db, deducted)
    except Exception as exc:
        errors.append(str(exc))
    if errors:
        logger.exception("Sale compensation was incomplete for sale %s", sale_id)
        raise RuntimeError(
            "Sale failed and inventory rollback was incomplete; "
            "reconcile the sale and stock movements."
        ) from RuntimeError("; ".join(errors))


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
    reason = str(reason or "").strip()
    if not reason:
        return {"success": False, "error": "A reason is required to void a sale."}
    if not ObjectId.is_valid(sale_id):
        return {"success": False, "error": "Invalid sale ID."}
    oid = ObjectId(sale_id)
    sale = db.sales.find_one({"_id": oid})
    if not sale:
        return {"success": False, "error": "Sale not found."}
    if sale["status"] != "completed":
        return {"success": False, "error": f"Cannot void a sale with status '{sale['status']}'."}

    now = utcnow()
    claim = db.sales.update_one(
        {"_id": oid, "status": "completed"},
        {"$set": {"status": "voiding", "updated_at": now}},
    )
    if claim.modified_count != 1:
        return {"success": False, "error": "Sale is already being voided or is no longer completed."}

    movements = []
    restored = []
    try:
        for item in sale.get("items", []):
            qty = int(item.get("quantity", 0))
            pid = item["product_id"]
            result = db.products.update_one(
                {"_id": pid},
                {"$inc": {"stock_qty": qty}, "$set": {"updated_at": now}},
            )
            if result.modified_count != 1:
                raise ValueError(f"Product '{pid}' no longer exists.")
            restored.append((pid, qty))
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

        updated = db.sales.update_one(
            {"_id": oid, "status": "voiding"},
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
        if updated.modified_count != 1:
            raise RuntimeError("Sale could not be finalized as voided.")
    except Exception as exc:
        compensation_errors = []
        try:
            db.stock_movements.delete_many(
                {"reference_id": oid, "reference_type": "sale_void"}
            )
        except Exception as compensation_exc:
            compensation_errors.append(str(compensation_exc))
        for pid, qty in reversed(restored):
            try:
                db.products.update_one({"_id": pid}, {"$inc": {"stock_qty": -qty}})
            except Exception as compensation_exc:
                compensation_errors.append(str(compensation_exc))
        try:
            db.sales.update_one(
                {"_id": oid, "status": "voiding"},
                {"$set": {"status": "completed", "updated_at": utcnow()}},
            )
        except Exception as compensation_exc:
            compensation_errors.append(str(compensation_exc))
        if compensation_errors:
            logger.exception("Sale void compensation was incomplete for %s", oid)
            return {
                "success": False,
                "error": (
                    f"Void failed ({exc}); rollback was incomplete. "
                    "Inspect this sale and its stock movements."
                ),
            }
        return {"success": False, "error": f"Void failed: {exc}"}
    return {"success": True, "invoice_number": sale["invoice_number"]}
