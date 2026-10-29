"""SmartStock – Authentication Service"""
from __future__ import annotations
from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from ..models.user import build_user_document, check_password, has_permission, ROLES
from ..utils import utcnow, mongo_doc_to_dict
from flask import current_app, has_app_context, session


def register_user(db: Database, data: dict) -> dict:
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    role = data.get("role", "sales")
    if not 3 <= len(username) <= 50:
        raise ValueError("Username must be between 3 and 50 characters.")
    if not username.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Username may only contain letters, digits, hyphens, and underscores.")
    if not 8 <= len(password.encode("utf-8")) <= 72:
        raise ValueError("Password must be between 8 and 72 bytes.")
    if role not in ROLES:
        raise ValueError("Invalid user role.")
    if db.users.find_one({"username": username}):
        raise ValueError(f"Username '{username}' is already taken.")
    bcrypt_log_rounds = (
        current_app.config.get("BCRYPT_LOG_ROUNDS", 12) if has_app_context() else 12
    )
    doc = build_user_document(data, bcrypt_log_rounds=bcrypt_log_rounds)
    try:
        result = db.users.insert_one(doc)
    except DuplicateKeyError as exc:
        if db.users.find_one({"username": username}):
            raise ValueError(f"Username '{username}' is already taken.") from exc
        if role == "owner":
            raise ValueError("An owner account already exists.") from exc
        raise
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
    current = db.users.find_one({"_id": ObjectId(user_id)}, {"role": 1})
    if not current:
        return False
    if current.get("role") == "owner" and role != "owner":
        if db.users.count_documents({"role": "owner"}) <= 1:
            return False
    result = db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": role, "updated_at": utcnow()}},
    )
    return result.modified_count > 0
