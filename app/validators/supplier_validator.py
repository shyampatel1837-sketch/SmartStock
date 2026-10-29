"""SmartStock – Supplier Validation"""
from __future__ import annotations
import re
from .base import require_fields


def validate_supplier(data: dict, is_update: bool = False) -> list[str]:
    errors: list[str] = []
    if not is_update:
        errors += require_fields(data, ["name"])

    if data.get("name") and len(str(data["name"]).strip()) < 2:
        errors.append("Supplier name must be at least 2 characters.")
    if data.get("name") and len(str(data["name"]).strip()) > 120:
        errors.append("Supplier name cannot exceed 120 characters.")

    if data.get("email"):
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', str(data["email"]).strip()):
            errors.append("Invalid email address.")

    if data.get("phone"):
        phone = re.sub(r'[\s\-\(\)\+]', '', str(data["phone"]))
        if not phone.isdigit() or len(phone) < 7:
            errors.append("Invalid phone number.")
    if data.get("status") and data["status"] not in ("active", "inactive"):
        errors.append("Select a valid supplier status.")

    return errors
