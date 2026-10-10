"""
SmartStock – Stock Movement Model

The stock_movements collection is the authoritative ledger for all
inventory changes. Every change to stock_qty MUST be accompanied by
a stock_movement record created in the same operation.

Movement types:
  purchase_receipt   – goods received from a supplier
  sale               – sold to a customer
  return_customer    – customer returned goods (stock restored)
  return_supplier    – goods returned to supplier (stock reduced)
  adjustment_up      – manual positive correction
  adjustment_down    – manual negative correction
  damage             – goods written off as damaged / defective
  opening_stock      – initial stock entry
"""
from bson import ObjectId
from ..utils import utcnow


MOVEMENT_TYPES = [
    "purchase_receipt",
    "sale",
    "return_customer",
    "return_supplier",
    "adjustment_up",
    "adjustment_down",
    "damage",
    "opening_stock",
]


def build_movement(
    product_id,
    movement_type: str,
    quantity_change: int,
    reference_id=None,
    reference_type: str = "",
    reason: str = "",
    actor=None,
    notes: str = "",
) -> dict:
    """
    Build a stock movement document.

    Args:
        product_id:      ObjectId of the product.
        movement_type:   One of MOVEMENT_TYPES.
        quantity_change: Positive for stock-in, negative for stock-out.
        reference_id:    ObjectId of the related sale, PO, or adjustment.
        reference_type:  'sale', 'purchase_order', 'adjustment', etc.
        reason:          Human-readable reason (required for adjustments).
        actor:           ObjectId of the user who caused the movement.
        notes:           Additional notes.
    """
    if movement_type not in MOVEMENT_TYPES:
        raise ValueError(f"Invalid movement type: {movement_type}")

    return {
        "product_id": ObjectId(product_id) if not isinstance(product_id, ObjectId) else product_id,
        "movement_type": movement_type,
        "quantity_change": int(quantity_change),
        "reference_id": reference_id,
        "reference_type": reference_type,
        "reason": str(reason).strip(),
        "actor": actor,
        "notes": str(notes).strip(),
        "created_at": utcnow(),
    }
