"""SmartStock – Main / Dashboard Routes"""
from flask import Blueprint, render_template, redirect, url_for, g, jsonify
from ..db import get_db, ping
from ..services.analytics_service import get_dashboard_summary
from ..models.user import has_permission
from .decorators import login_required, permission_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    if g.current_user:
        endpoint = (
            "main.dashboard"
            if has_permission(g.current_user.get("role", ""), "analytics", "read")
            else "sales.index"
        )
        return redirect(url_for(endpoint))
    return redirect(url_for("auth.login"))


@main_bp.route("/dashboard")
@login_required
@permission_required("analytics", "read")
def dashboard():
    db = get_db()
    summary = get_dashboard_summary(db)
    return render_template("dashboard.html", summary=summary)


@main_bp.route("/health")
def health():
    database_available = ping()
    return jsonify({
        "status": "ok" if database_available else "unavailable",
        "db": database_available,
    }), 200 if database_available else 503
