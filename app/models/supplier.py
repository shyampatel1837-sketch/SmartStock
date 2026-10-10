"""
SmartStock – Supplier Model
"""
from ..utils import utcnow


def build_supplier_document(data: dict) -> dict:
    now = utcnow()
    return {
        "name": str(data["name"]).strip(),
        "contact_person": str(data.get("contact_person", "")).strip(),
        "phone": str(data.get("phone", "")).strip(),
        "email": str(data.get("email", "")).strip().lower(),
        "address": str(data.get("address", "")).strip(),
        "gst_number": str(data.get("gst_number", "")).strip().upper(),
        "notes": str(data.get("notes", "")).strip(),
        "status": data.get("status", "active"),
        "created_at": now,
        "updated_at": now,
    }


def update_fields(data: dict) -> dict:
    updatable = ["name", "contact_person", "phone", "email",
                 "address", "gst_number", "notes", "status"]
    result = {"updated_at": utcnow()}
    for field in updatable:
        if field in data and data[field] is not None:
            result[field] = data[field]
    return result
