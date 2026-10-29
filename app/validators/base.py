"""
SmartStock – Base Validation Helpers
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def require_fields(data: dict, fields: list[str]) -> list[str]:
    errors = []
    for field in fields:
        if not data.get(field) and data.get(field) != 0:
            errors.append(f"'{field}' is required.")
    return errors


def validate_positive_decimal(value, label: str,
                               allow_zero: bool = False) -> str | None:
    try:
        d = Decimal(str(value))
        if not d.is_finite():
            return f"{label} must be a finite number."
        if allow_zero and d < 0:
            return f"{label} cannot be negative."
        if not allow_zero and d <= 0:
            return f"{label} must be greater than zero."
    except (InvalidOperation, TypeError, ValueError):
        return f"{label} must be a valid number."
    return None


def validate_quantity(value, label: str = "Quantity",
                      min_val: int = 1) -> str | None:
    try:
        if isinstance(value, bool):
            raise ValueError
        quantity = Decimal(str(value))
        if not quantity.is_finite() or quantity != quantity.to_integral_value():
            raise ValueError
        q = int(quantity)
        if q < min_val:
            return f"{label} must be at least {min_val}."
    except (TypeError, ValueError):
        return f"{label} must be a whole number."
    return None
