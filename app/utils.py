"""
SmartStock – Shared Utilities
-------------------------------
Helper functions used across the application.
"""
from __future__ import annotations

import re
import datetime
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from bson import ObjectId


# ──────────────────────────────────────────────────────────────────────────────
# ObjectId helpers
# ──────────────────────────────────────────────────────────────────────────────

def to_object_id(value: str) -> ObjectId | None:
    """Convert a string to ObjectId; return None if invalid."""
    try:
        return ObjectId(value)
    except Exception:
        return None


def is_valid_object_id(value: str) -> bool:
    return ObjectId.is_valid(value)


# ──────────────────────────────────────────────────────────────────────────────
# Monetary helpers  (use Decimal throughout; never float for money)
# ──────────────────────────────────────────────────────────────────────────────

TWO_PLACES = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """Safely convert any numeric-like value to a two-decimal Decimal."""
    try:
        return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def decimal_to_float(value: Decimal) -> float:
    """Convert Decimal to float for JSON serialization (analytics only)."""
    return float(value)


def money_str(value, symbol: str = "₹") -> str:
    """Format a monetary value as a human-readable string."""
    d = to_decimal(value)
    return f"{symbol} {d:,.2f}"


# ──────────────────────────────────────────────────────────────────────────────
# Invoice / reference number generation
# ──────────────────────────────────────────────────────────────────────────────

def generate_invoice_number(prefix: str, db, collection: str = "sales") -> str:
    """
    Generate a unique, sequential invoice number using MongoDB's atomic
    findOneAndUpdate on a counters collection.

    Format: {PREFIX}-{YYYYMM}-{NNNNNN}
    e.g.    INV-202410-000042

    The counter resets per year-month so invoice numbers stay short.
    """
    now = datetime.datetime.utcnow()
    period = now.strftime("%Y%m")
    counter_id = f"{prefix}-{period}"

    result = db["counters"].find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,  # pymongo ReturnDocument.AFTER
    )
    seq = result["seq"]
    return f"{prefix}-{period}-{seq:06d}"


def generate_po_reference(db) -> str:
    now = datetime.datetime.utcnow()
    period = now.strftime("%Y%m")
    counter_id = f"PO-{period}"
    result = db["counters"].find_one_and_update(
        {"_id": counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return f"PO-{period}-{result['seq']:06d}"


# ──────────────────────────────────────────────────────────────────────────────
# Date helpers
# ──────────────────────────────────────────────────────────────────────────────

def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def parse_date(value: str) -> datetime.datetime | None:
    """Parse ISO-8601 date string; return None on failure."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def start_of_day(dt: datetime.datetime) -> datetime.datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(dt: datetime.datetime) -> datetime.datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


# ──────────────────────────────────────────────────────────────────────────────
# Pagination
# ──────────────────────────────────────────────────────────────────────────────

class PaginationMeta:
    def __init__(self, total: int, page: int, per_page: int):
        self.total = total
        self.page = page
        self.per_page = per_page
        self.total_pages = math.ceil(total / per_page) if per_page else 1
        self.has_prev = page > 1
        self.has_next = page < self.total_pages

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "page": self.page,
            "per_page": self.per_page,
            "total_pages": self.total_pages,
            "has_prev": self.has_prev,
            "has_next": self.has_next,
        }


def paginate(query_cursor, page: int, per_page: int = 20):
    """Apply skip/limit to a PyMongo cursor and return (items, meta)."""
    page = max(1, page)
    per_page = max(1, min(per_page, 100))  # cap at 100
    skip = (page - 1) * per_page
    items = list(query_cursor.skip(skip).limit(per_page))
    return items


def safe_int(value, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────────────────────────────────────
# JSON serialization helper
# ──────────────────────────────────────────────────────────────────────────────

def mongo_doc_to_dict(doc: dict) -> dict:
    """
    Convert a MongoDB document to a JSON-serializable dict.
    Converts ObjectId → str, datetime → ISO string, Decimal128 → float.
    """
    if doc is None:
        return {}
    result = {}
    for key, value in doc.items():
        result[key] = _convert_value(value)
    return result


def _convert_value(value):
    from bson import Decimal128
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _convert_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert_value(i) for i in value]
    return value


# ──────────────────────────────────────────────────────────────────────────────
# Input sanitization
# ──────────────────────────────────────────────────────────────────────────────

def sanitize_string(value: str, max_length: int = 500) -> str:
    """Strip whitespace and truncate to max_length."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def slugify(value: str) -> str:
    """Convert a string to a safe lowercase slug."""
    value = value.lower().strip()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[\s_-]+", "-", value)
    return value.strip("-")
