"""
SmartStock – Sale Model

Each completed sale stores:
  - A unique invoice number (generated atomically)
  - Line items with a SNAPSHOT of product name/SKU/price at time of sale
    so historical invoices survive catalogue changes.
  - Calculated totals using Decimal arithmetic.

Status: completed → returned | voided
Voiding reverses the stock deduction via the service layer.
"""
from __future__ import annotations
from bson import ObjectId, Decimal128
from ..utils import to_decimal, utcnow


PAYMENT_METHODS = ["cash", "card", "upi", "bank_transfer", "credit", "other"]
SALE_STATUSES   = ["completed", "voided", "returned", "partial_return"]


def build_sale_document(data: dict, invoice_number: str,
                        tax_percent: float = 18.0) -> dict:
    now = utcnow()
    items, subtotal = _build_line_items(data.get("items", []))
    discount = to_decimal(data.get("discount_amount", 0))
    taxable = subtotal - discount
    tax_amount = (taxable * to_decimal(tax_percent) / to_decimal(100)).quantize(
        to_decimal(0.01)  # type: ignore[arg-type]
    )
    total = taxable + tax_amount

    return {
        "invoice_number": invoice_number,
        "items": items,
        "subtotal": Decimal128(str(subtotal)),
        "discount_amount": Decimal128(str(discount)),
        "tax_percent": float(tax_percent),
        "tax_amount": Decimal128(str(tax_amount)),
        "total_amount": Decimal128(str(total)),
        "payment_method": data.get("payment_method", "cash"),
        "payment_reference": str(data.get("payment_reference", "")).strip(),
        "customer_name": str(data.get("customer_name", "Walk-in")).strip(),
        "customer_phone": str(data.get("customer_phone", "")).strip(),
        "notes": str(data.get("notes", "")).strip(),
        "status": "completed",
        "sale_date": now,
        "created_by": data.get("created_by"),   # user ObjectId
        "created_at": now,
        "updated_at": now,
        # Idempotency key (optional: client-supplied UUID to prevent duplicates)
        "idempotency_key": data.get("idempotency_key"),
    }


def _build_line_items(items: list):
    """Build validated line items and return (items_list, subtotal)."""
    from decimal import Decimal
    result = []
    subtotal = Decimal("0.00")
    for item in items:
        qty   = max(1, int(item.get("quantity", 1)))
        price = to_decimal(item.get("unit_price", 0))
        disc  = to_decimal(item.get("discount_amount", 0))
        line  = to_decimal(qty) * price - disc
        subtotal += line
        result.append({
            "product_id":   ObjectId(item["product_id"]),
            # Historical snapshots:
            "product_sku":  str(item.get("product_sku", "")).strip().upper(),
            "product_name": str(item.get("product_name", "")).strip(),
            "unit_price":   Decimal128(str(price)),
            "quantity":     qty,
            "discount_amount": Decimal128(str(disc)),
            "line_total":   Decimal128(str(line)),
        })
    return result, subtotal
