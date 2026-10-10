"""SmartStock – Route Decorators"""
from functools import wraps
from flask import redirect, url_for, abort, flash, g


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not g.current_user:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper


def permission_required(resource: str, action: str):
    """Decorator for route-level RBAC checks."""
    from ..models.user import has_permission

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not g.current_user:
                return redirect(url_for("auth.login"))
            if not has_permission(g.current_user.get("role", ""), resource, action):
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator
