"""SmartStock – Settings & User Management Routes"""
from flask import (Blueprint, request, render_template, redirect,
                   url_for, flash, g)
from ..db import get_db
from ..services.auth_service import list_users, update_user_role, register_user
from ..models.user import ROLES
from .decorators import login_required, permission_required

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/")
@login_required
@permission_required("settings", "read")
def index():
    return render_template("settings/index.html")


@settings_bp.route("/users")
@login_required
@permission_required("users", "read")
def users():
    db = get_db()
    user_list = list_users(db)
    return render_template("settings/users.html", users=user_list, roles=ROLES)


@settings_bp.route("/users/<user_id>/role", methods=["POST"])
@login_required
@permission_required("users", "write")
def update_role(user_id):
    db = get_db()
    role = request.form.get("role")
    if update_user_role(db, user_id, role):
        flash("Role updated.", "success")
    else:
        flash("Could not update role.", "error")
    return redirect(url_for("settings.users"))


@settings_bp.route("/users/new", methods=["GET", "POST"])
@login_required
@permission_required("users", "write")
def new_user():
    db = get_db()
    if request.method == "POST":
        data = {
            "username": request.form.get("username"),
            "full_name": request.form.get("full_name"),
            "email": request.form.get("email"),
            "password": request.form.get("password"),
            "role": request.form.get("role", "sales"),
        }
        try:
            register_user(db, data)
            flash("User account created.", "success")
            return redirect(url_for("settings.users"))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("settings/new_user.html", roles=ROLES)
