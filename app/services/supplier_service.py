"""SmartStock – Supplier Service"""
from __future__ import annotations
import math
from bson import ObjectId
from pymongo.database import Database
from ..models.supplier import build_supplier_document, update_fields
from ..utils import utcnow, mongo_doc_to_dict


def create_supplier(db: Database, data: dict) -> dict:
    name = str(data["name"]).strip()
    if db.suppliers.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}}):
        raise ValueError(f"Supplier '{name}' already exists.")
    doc = build_supplier_document(data)
    result = db.suppliers.insert_one(doc)
    doc["_id"] = result.inserted_id
    return mongo_doc_to_dict(doc)


def get_supplier(db: Database, supplier_id: str) -> dict | None:
    if not ObjectId.is_valid(supplier_id):
        return None
    doc = db.suppliers.find_one({"_id": ObjectId(supplier_id)})
    return mongo_doc_to_dict(doc) if doc else None


def list_suppliers(db: Database, status: str = "active",
                   page: int = 1, per_page: int = 20) -> dict:
    query = {"status": status} if status else {}
    total = db.suppliers.count_documents(query)
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    skip = (page - 1) * per_page
    items = [
        mongo_doc_to_dict(d)
        for d in db.suppliers.find(query).sort("name", 1).skip(skip).limit(per_page)
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


def update_supplier(db: Database, supplier_id: str, data: dict) -> dict | None:
    if not ObjectId.is_valid(supplier_id):
        return None
    oid = ObjectId(supplier_id)
    if data.get("name"):
        name = str(data["name"]).strip()
        existing = db.suppliers.find_one(
            {"name": {"$regex": f"^{name}$", "$options": "i"}, "_id": {"$ne": oid}}
        )
        if existing:
            raise ValueError(f"Supplier name '{name}' is already in use.")
    fields = update_fields(data)
    db.suppliers.update_one({"_id": oid}, {"$set": fields})
    return get_supplier(db, supplier_id)


def delete_supplier(db: Database, supplier_id: str) -> dict:
    if not ObjectId.is_valid(supplier_id):
        return {"deleted": False, "reason": "Invalid supplier ID."}
    oid = ObjectId(supplier_id)
    has_orders = db.purchase_orders.find_one({"supplier_id": oid})
    has_products = db.products.find_one({"supplier_id": oid})
    if has_orders or has_products:
        return {
            "deleted": False,
            "reason": "Cannot delete: supplier has purchase orders or products. Set status to 'inactive' instead.",
        }
    db.suppliers.delete_one({"_id": oid})
    return {"deleted": True, "reason": "Supplier deleted."}
