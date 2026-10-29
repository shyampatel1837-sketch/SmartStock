"""SmartStock – Auth Routes"""
from flask import Blueprint, request, redirect, url_for, session, render_template, flash, g
from bson import ObjectId
from ..db import get_db
from ..services.auth_service import authenticate, register_user, get_current_user
from ..models.user import has_permission

auth_bp = Blueprint("auth", __name__)


@auth_bp.before_app_request
def load_user():
    g.current_user = None
    user_id = session.get("user_id")
    if user_id and ObjectId.is_valid(user_id):
        g.current_user = get_current_user(get_db())
    elif user_id:
        session.pop("user_id", None)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user:
        destination = (
            "main.dashboard"
            if has_permission(g.current_user.get("role", ""), "analytics", "read")
            else "sales.index"
        )
        return redirect(url_for(destination))
    if request.method == "POST":
        db = get_db()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = authenticate(db, username, password)
        if user:
            session.clear()
            session["user_id"] = user["_id"]
            session.permanent = True
            flash(f"Welcome back, {user.get('full_name') or user['username']}!", "success")
            destination = (
                "main.dashboard"
                if has_permission(user.get("role", ""), "analytics", "read")
                else "sales.index"
            )
            return redirect(url_for(destination))
        flash("Invalid username or password.", "error")
    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Only accessible when no owner account exists (first-time setup)."""
    db = get_db()
    owner_exists = db.users.find_one({"role": "owner"})
    if owner_exists and not (g.current_user and g.current_user.get("role") == "owner"):
        flash("Account registration is restricted to the store owner.", "error")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        data = {
            "username": request.form.get("username"),
            "full_name": request.form.get("full_name"),
            "email": request.form.get("email"),
            "password": request.form.get("password"),
            "role": "owner" if not owner_exists else request.form.get("role", "sales"),
        }
        try:
            register_user(db, data)
            flash("Account created. Please log in.", "success")
            return redirect(url_for("auth.login"))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("auth/register.html")
