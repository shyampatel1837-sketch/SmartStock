"""SmartStock – Main / Dashboard Routes"""
from flask import Blueprint, render_template, redirect, url_for, g, jsonify
from ..db import get_db, ping
from ..services.analytics_service import get_dashboard_summary
from .decorators import login_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    if g.current_user:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    summary = get_dashboard_summary(db)
    return render_template("dashboard.html", summary=summary)


@main_bp.route("/health")
def health():
    return jsonify({"status": "ok", "db": ping()})
