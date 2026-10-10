"""
SmartStock – MongoDB Index Definitions
----------------------------------------
All indexes are defined here so they can be created idempotently
at startup and in scripts/init_db.py.

Each entry documents:
  - collection
  - fields (pymongo index spec)
  - options (unique, sparse, background, name, …)
  - purpose (comment for future maintainers)

Performance note: indexes speed up the listed queries but add write
overhead. Indexes marked unique enforce data-integrity constraints.
"""
from __future__ import annotations

import logging
from flask import Flask
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.database import Database

from .db import get_db

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Index specifications
# Format: (collection, key_spec, options, purpose_comment)
# ──────────────────────────────────────────────────────────────────────────────
INDEX_SPECS = [
    # ── products ────────────────────────────────────────────────────────────
    (
        "products",
        [("sku", ASCENDING)],
        {"unique": True, "name": "sku_unique"},
        "Unique SKU prevents duplicate products; supports lookup by SKU",
    ),
    (
        "products",
        [("category", ASCENDING), ("status", ASCENDING)],
        {"name": "category_status"},
        "Supports category-filtered product listings with active/inactive filter",
    ),
    (
        "products",
        [("brand", ASCENDING)],
        {"name": "brand"},
        "Supports brand-filtered product listings",
    ),
    (
        "products",
        [("category", ASCENDING), ("selling_price", ASCENDING)],
        {"name": "category_price"},
        "Supports price-range queries within a category",
    ),
    (
        "products",
        [("stock_qty", ASCENDING)],
        {"name": "stock_qty"},
        "Supports low-stock and out-of-stock queries efficiently",
    ),
    (
        "products",
        [("name", TEXT), ("description", TEXT), ("brand", TEXT)],
        {"name": "product_text_search", "default_language": "english"},
        "Full-text search across product name, description, and brand",
    ),
    # ── suppliers ────────────────────────────────────────────────────────────
    (
        "suppliers",
        [("name", ASCENDING)],
        {"unique": True, "name": "supplier_name_unique"},
        "Unique supplier name; supports supplier lookup",
    ),
    (
        "suppliers",
        [("status", ASCENDING)],
        {"name": "supplier_status"},
        "Filters active/inactive suppliers",
    ),
    # ── purchase_orders ──────────────────────────────────────────────────────
    (
        "purchase_orders",
        [("reference", ASCENDING)],
        {"unique": True, "name": "po_reference_unique"},
        "Unique purchase reference prevents duplicate PO processing",
    ),
    (
        "purchase_orders",
        [("supplier_id", ASCENDING), ("order_date", DESCENDING)],
        {"name": "po_supplier_date"},
        "Supplier purchase history ordered by date",
    ),
    (
        "purchase_orders",
        [("status", ASCENDING), ("order_date", DESCENDING)],
        {"name": "po_status_date"},
        "Pending / received order queries",
    ),
    # ── sales ────────────────────────────────────────────────────────────────
    (
        "sales",
        [("invoice_number", ASCENDING)],
        {"unique": True, "name": "invoice_unique"},
        "Unique invoice number for idempotency and lookup",
    ),
    (
        "sales",
        [("sale_date", DESCENDING)],
        {"name": "sale_date"},
        "Recent-sales queries and date-range aggregations",
    ),
    (
        "sales",
        [("status", ASCENDING)],
        {"name": "sale_status"},
        "Filters completed / voided / returned sales",
    ),
    # ── stock_movements ──────────────────────────────────────────────────────
    (
        "stock_movements",
        [("product_id", ASCENDING), ("created_at", DESCENDING)],
        {"name": "movement_product_date"},
        "Stock history per product ordered by date",
    ),
    (
        "stock_movements",
        [("movement_type", ASCENDING), ("created_at", DESCENDING)],
        {"name": "movement_type_date"},
        "Reports by movement type (sale, receipt, adjustment, …)",
    ),
    (
        "stock_movements",
        [("reference_id", ASCENDING)],
        {"name": "movement_reference"},
        "Look up movements associated with a sale, PO, or adjustment",
    ),
    # ── reviews ──────────────────────────────────────────────────────────────
    (
        "reviews",
        [("product_id", ASCENDING), ("review_date", DESCENDING)],
        {"name": "review_product_date"},
        "Reviews for a product ordered by recency",
    ),
    (
        "reviews",
        [("rating", ASCENDING)],
        {"name": "review_rating"},
        "Rating distribution queries",
    ),
    (
        "reviews",
        [("status", ASCENDING)],
        {"name": "review_status"},
        "Filter pending / approved / rejected reviews",
    ),
    # ── users ────────────────────────────────────────────────────────────────
    (
        "users",
        [("username", ASCENDING)],
        {"unique": True, "name": "username_unique"},
        "Unique username for authentication",
    ),
    (
        "users",
        [("role", ASCENDING)],
        {"name": "user_role"},
        "Role-based access-control queries",
    ),
]


def ensure_indexes(app: Flask) -> None:
    """
    Create all defined indexes idempotently.
    Safe to call multiple times; existing indexes are left unchanged.
    """
    db: Database = get_db()
    created = 0
    skipped = 0

    for collection_name, key_spec, options, purpose in INDEX_SPECS:
        coll = db[collection_name]
        try:
            coll.create_index(key_spec, **options)
            logger.debug(
                "Index '%s' on '%s' ensured. Purpose: %s",
                options.get("name"),
                collection_name,
                purpose,
            )
            created += 1
        except Exception as exc:
            # ConflictingIndexes, etc. – log and continue
            logger.warning(
                "Could not create index '%s' on '%s': %s",
                options.get("name"),
                collection_name,
                exc,
            )
            skipped += 1

    logger.info(
        "Index initialisation complete. Created/ensured: %d, Skipped: %d",
        created,
        skipped,
    )


def list_indexes(db: Database) -> dict:
    """Return a dict of {collection: [index_info, …]} for all managed collections."""
    result = {}
    collections = {spec[0] for spec in INDEX_SPECS}
    for coll_name in sorted(collections):
        coll = db[coll_name]
        try:
            result[coll_name] = list(coll.list_indexes())
        except Exception as exc:
            result[coll_name] = [{"error": str(exc)}]
    return result
