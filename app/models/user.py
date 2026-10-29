"""
SmartStock – User Model

Roles:
  owner    – full access including settings and user management
  manager  – all operations except system settings and user management
  sales    – sales workflow and customer reviews only
  inventory – purchasing, stock adjustments, but not sales or settings

Passwords are hashed with bcrypt before storage.
Plain-text passwords are never stored.
"""
import bcrypt
from ..utils import utcnow

ROLES = ["owner", "manager", "sales", "inventory"]

ROLE_PERMISSIONS = {
    "owner": {
        "products": ["read", "write", "delete"],
        "suppliers": ["read", "write", "delete"],
        "purchases": ["read", "write"],
        "sales": ["read", "write", "void"],
        "inventory": ["read", "write"],
        "reviews": ["read", "write", "moderate"],
        "analytics": ["read"],
        "settings": ["read", "write"],
        "users": ["read", "write", "delete"],
    },
    "manager": {
        "products": ["read", "write"],
        "suppliers": ["read", "write"],
        "purchases": ["read", "write"],
        "sales": ["read", "write", "void"],
        "inventory": ["read", "write"],
        "reviews": ["read", "write", "moderate"],
        "analytics": ["read"],
        "settings": ["read"],
        "users": ["read"],
    },
    "sales": {
        "products": ["read"],
        "suppliers": [],
        "purchases": [],
        "sales": ["read", "write"],
        "inventory": ["read"],
        "reviews": ["read", "write"],
        "analytics": [],
        "settings": [],
        "users": [],
    },
    "inventory": {
        "products": ["read", "write"],
        "suppliers": ["read", "write"],
        "purchases": ["read", "write"],
        "sales": [],
        "inventory": ["read", "write"],
        "reviews": ["read"],
        "analytics": ["read"],
        "settings": [],
        "users": [],
    },
}


def build_user_document(data: dict, bcrypt_log_rounds: int = 12) -> dict:
    now = utcnow()
    plain = str(data["password"])
    hashed = bcrypt.hashpw(
        plain.encode(), bcrypt.gensalt(rounds=bcrypt_log_rounds)
    )
    return {
        "username": str(data["username"]).strip().lower(),
        "full_name": str(data.get("full_name", "")).strip(),
        "email": str(data.get("email", "")).strip().lower(),
        "password_hash": hashed.decode(),
        "role": data.get("role", "sales"),
        "is_active": True,
        "last_login": None,
        "created_at": now,
        "updated_at": now,
    }


def check_password(stored_hash: str, plain: str) -> bool:
    return bcrypt.checkpw(plain.encode(), stored_hash.encode())


def has_permission(role: str, resource: str, action: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, {})
    return action in perms.get(resource, [])
