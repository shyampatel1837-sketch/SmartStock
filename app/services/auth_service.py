"""SmartStock – Authentication Service"""
from __future__ import annotations
from bson import ObjectId
from pymongo.database import Database
from ..models.user import build_user_document, check_password, has_permission, ROLES
from ..utils import utcnow, mongo_doc_to_dict
from flask import session


def register_user(db: Database, data: dict) -> dict:
    username = str(data.get("username", "")).strip().lower()
    if db.users.find_one({"username": username}):
        raise ValueError(f"Username '{username}' is already taken.")
    doc = build_user_document(data)
    result = db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    # Never return the password hash to the caller
    doc.pop("password_hash", None)
    return mongo_doc_to_dict(doc)


def authenticate(db: Database, username: str, password: str) -> dict | None:
    """Return user dict (without hash) if credentials are valid, else None."""
    user = db.users.find_one({"username": username.strip().lower(), "is_active": True})
    if not user:
        return None
    if not check_password(user["password_hash"], password):
        return None
    db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login": utcnow()}})
    user.pop("password_hash", None)
    return mongo_doc_to_dict(user)


def get_current_user(db: Database) -> dict | None:
    user_id = session.get("user_id")
    if not user_id or not ObjectId.is_valid(user_id):
        return None
    user = db.users.find_one({"_id": ObjectId(user_id), "is_active": True})
    if not user:
        return None
    user.pop("password_hash", None)
    return mongo_doc_to_dict(user)


def require_permission(resource: str, action: str):
    """Flask decorator factory for route-level permission checks."""
    from functools import wraps
    from flask import abort, g

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if not user:
                abort(401)
            if not has_permission(user.get("role", ""), resource, action):
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def list_users(db: Database) -> list[dict]:
    users = []
    for u in db.users.find({}, {"password_hash": 0}).sort("username", 1):
        users.append(mongo_doc_to_dict(u))
    return users


def update_user_role(db: Database, user_id: str, role: str) -> bool:
    if not ObjectId.is_valid(user_id) or role not in ROLES:
        return False
    result = db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": role, "updated_at": utcnow()}},
    )
    return result.modified_count > 0
