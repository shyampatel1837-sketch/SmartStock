"""
SmartStock – Product Model
Defines the document structure for the `products` collection.

Design decisions:
  - Common fields are at the top level.
  - Category-specific technical specifications are stored in an embedded
    `specs` sub-document, keyed differently per category.
    This demonstrates MongoDB's flexible schema capability.
  - Variant information (size, colour, storage) is stored in an embedded
    `variants` array for products that need it (e.g. phones with 128 GB / 256 GB).
  - Stock quantity is stored here for fast dashboard reads but is always
    modified through stock movements to maintain a consistent ledger.
  - Purchase cost and selling price are stored as strings that represent
    exact decimal values (serialised from Python Decimal).
    PyMongo's Decimal128 is used when writing to MongoDB.

Relationships:
  - product.supplier_id → suppliers._id
"""
from __future__ import annotations

import datetime
from typing import Any
from bson import ObjectId, Decimal128
from ..utils import to_decimal, utcnow


#  Valid categories 
CATEGORIES = [
    "Smartphones",
    "Laptops",
    "Headphones & Speakers",
    "Keyboards & Mice",
    "Monitors",
    "Chargers & Cables",
    "Computer Components",
    "Power Banks & Storage",
    "Printers",
    "Accessories",
    "Other",
]

PRODUCT_STATUSES = ["active", "inactive", "discontinued"]
SPECIFICATION_FIELDS = [
    "ram_gb", "storage_gb", "screen_size_inch", "battery_mah", "os",
    "processor", "camera_mp", "connectivity", "cpu", "gpu",
    "display_resolution", "weight_kg", "operating_system", "resolution",
    "refresh_rate_hz", "panel_type", "response_time_ms", "ports",
    "driver_size_mm", "frequency_response", "impedance_ohm",
    "noise_cancellation", "wireless", "battery_life_hr", "wattage_w",
    "connector_type", "charging_standard", "cable_length_m", "voltage_v",
    "ampere_a", "print_technology", "ppm", "max_paper_size", "duplex",
    "wireless_print",
]


def build_product_document(data: dict) -> dict:
    """
    Build a validated product document ready for insertion into MongoDB.

    Args:
        data: Dict of raw form / API values.

    Returns:
        MongoDB-ready dict with Decimal128 monetary values.
    """
    now = utcnow()

    cost = to_decimal(data.get("purchase_cost", 0))
    price = to_decimal(data.get("selling_price", 0))
    stock = int(data.get("stock_qty", 0))
    reorder = int(data.get("reorder_threshold", 5))

    doc = {
        #  Identification ─
        "sku": str(data["sku"]).strip().upper(),
        "name": str(data["name"]).strip(),
        "brand": str(data.get("brand", "")).strip(),
        "category": str(data.get("category", "Other")).strip(),
        "subcategory": str(data.get("subcategory", "")).strip(),
        "description": str(data.get("description", "")).strip(),

        #  Pricing (Decimal128 for exact arithmetic in MongoDB) ─
        "purchase_cost": Decimal128(str(cost)),
        "selling_price": Decimal128(str(price)),

        #  Inventory ─
        "stock_qty": stock,
        "reorder_threshold": reorder,

        #  Supplier reference ─
        "supplier_id": (
            ObjectId(data["supplier_id"])
            if data.get("supplier_id") and ObjectId.is_valid(str(data["supplier_id"]))
            else None
        ),

        #  Warranty 
        "warranty_months": int(data.get("warranty_months", 0)),
        "warranty_terms": str(data.get("warranty_terms", "")).strip(),

        #  Category-specific specs (flexible sub-document) 
        "specs": _build_specs(data),

        #  Optional variants 
        "variants": data.get("variants", []),

        #  Status 
        "status": data.get("status", "active"),

        #  Timestamps 
        "created_at": now,
        "updated_at": now,
    }

    return doc


def _build_specs(data: dict) -> dict:
    """
    Build the category-specific specs sub-document.
    Only includes keys that were supplied and non-empty.
    """
    specs: dict[str, Any] = {}
    fields_by_category = {
        "Smartphones": [
            "ram_gb", "storage_gb", "screen_size_inch", "battery_mah",
            "os", "processor", "camera_mp", "connectivity",
        ],
        "Laptops": [
            "ram_gb", "storage_gb", "screen_size_inch", "cpu", "gpu",
            "display_resolution", "weight_kg", "operating_system",
        ],
        "Headphones & Speakers": [
            "driver_size_mm", "frequency_response", "impedance_ohm",
            "noise_cancellation", "wireless", "battery_life_hr", "connectivity",
        ],
        "Keyboards & Mice": ["connectivity", "wireless"],
        "Monitors": [
            "screen_size_inch", "resolution", "refresh_rate_hz", "panel_type",
            "response_time_ms", "ports",
        ],
        "Chargers & Cables": [
            "wattage_w", "connector_type", "charging_standard",
            "cable_length_m", "voltage_v", "ampere_a",
        ],
        "Computer Components": [
            "ram_gb", "storage_gb", "processor", "cpu", "gpu",
        ],
        "Power Banks & Storage": [
            "storage_gb", "battery_mah", "wattage_w", "connector_type",
            "charging_standard",
        ],
        "Printers": [
            "print_technology", "ppm", "max_paper_size", "duplex",
            "wireless_print", "connectivity",
        ],
        "Accessories": ["connectivity"],
        "Other": ["connectivity"],
    }
    allowed_fields = fields_by_category.get(data.get("category", "Other"), [])
    for field in allowed_fields:
        if data.get(field) not in (None, "", "0"):
            specs[field] = data[field]

    return specs


def update_fields(data: dict) -> dict:
    """
    Build the $set dict for a product update operation.
    Only includes fields present in data; always updates `updated_at`.
    """
    updatable = [
        "name", "brand", "category", "subcategory", "description",
        "warranty_months", "warranty_terms", "status",
        "reorder_threshold",
    ]
    result: dict[str, Any] = {"updated_at": utcnow()}

    for field in updatable:
        if field in data and data[field] is not None:
            result[field] = data[field]

    if "purchase_cost" in data:
        result["purchase_cost"] = Decimal128(str(to_decimal(data["purchase_cost"])))

    if "selling_price" in data:
        result["selling_price"] = Decimal128(str(to_decimal(data["selling_price"])))

    if "supplier_id" in data:
        result["supplier_id"] = (
            ObjectId(data["supplier_id"]) if data["supplier_id"] else None
        )

    # Rebuild specs if any spec field changed
    specs = _build_specs(data)
    if specs:
        for k, v in specs.items():
            result[f"specs.{k}"] = v

    return result
