"""
SmartStock – Purchase Order Model

Status lifecycle:  draft → confirmed → received → cancelled
A PO can only increase stock when it moves to 'received'.
Idempotency: the received_at timestamp and the status flag together
prevent double-receipt; the service layer also checks this before
incrementing stock.
"""
from __future__ import annotations
import datetime
from bson import ObjectId, Decimal128
from ..utils import to_decimal, utcnow


PO_STATUSES = ["draft", "confirmed", "partially_received", "received", "cancelled"]


def build_po_document(data: dict, reference: str) -> dict:
    now = utcnow()
    items = _build_line_items(data.get("items", []))
    subtotal = sum(
        to_decimal(i["quantity"]) * to_decimal(i["unit_price"])
        for i in data.get("items", [])
    )
    discount = to_decimal(data.get("discount_amount", 0))
    tax_amount = to_decimal(data.get("tax_amount", 0))
    total = subtotal - discount + tax_amount

    return {
        "reference": reference,
        "supplier_id": ObjectId(data["supplier_id"]),
        "items": items,
        "subtotal": Decimal128(str(subtotal)),
        "discount_amount": Decimal128(str(discount)),
        "tax_amount": Decimal128(str(tax_amount)),
        "total_amount": Decimal128(str(total)),
        "currency": data.get("currency", "INR"),
        "order_date": _parse_date(data.get("order_date")) or now,
        "expected_date": _parse_date(data.get("expected_date")),
        "status": "draft",
        "notes": str(data.get("notes", "")).strip(),
        "received_at": None,
        "received_by": None,
        "created_at": now,
        "updated_at": now,
    }


def _build_line_items(items: list) -> list:
    result = []
    for item in items:
        qty = max(1, int(item.get("quantity", 1)))
        price = to_decimal(item.get("unit_price", 0))
        result.append({
            "product_id": ObjectId(item["product_id"]),
            # snapshot for historical accuracy
            "product_sku": str(item.get("product_sku", "")).strip().upper(),
            "product_name": str(item.get("product_name", "")).strip(),
            "quantity": qty,
            "received_quantity": 0,
            "unit_price": Decimal128(str(price)),
            "line_total": Decimal128(str(to_decimal(qty) * price)),
        })
    return result


def _parse_date(value) -> datetime.datetime | None:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None
