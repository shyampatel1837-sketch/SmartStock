"""SmartStock – Analytics Routes"""
from flask import Blueprint, request, render_template, jsonify, g
from ..db import get_db
from ..services.analytics_service import (
    get_dashboard_summary, sales_over_time, brand_counts,
    stock_movement_summary, _top_selling_products, _revenue_by_category,
    _inventory_value,
)
from ..utils import parse_date, start_of_day, end_of_day, utcnow, safe_int
from .decorators import login_required, permission_required
import datetime

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/")
@login_required
@permission_required("analytics", "read")
def index():
    db = get_db()
    now = utcnow()
    default_from = (now - datetime.timedelta(days=29)).strftime("%Y-%m-%d")
    default_to = now.strftime("%Y-%m-%d")

    date_from_str = request.args.get("date_from", default_from)
    date_to_str   = request.args.get("date_to",   default_to)
    group_by      = request.args.get("group_by", "day")

    date_from = start_of_day(parse_date(date_from_str) or now - datetime.timedelta(days=29))
    date_to   = end_of_day(parse_date(date_to_str) or now)

    revenue_chart = sales_over_time(db, date_from, date_to, group_by)
    top_products  = _top_selling_products(db, limit=10, date_from=date_from, date_to=date_to)
    by_category   = _revenue_by_category(db, date_from=date_from, date_to=date_to)
    inv_value     = _inventory_value(db)
    brands        = brand_counts(db)
    movements     = stock_movement_summary(db, days=30)

    return render_template(
        "analytics/index.html",
        revenue_chart=revenue_chart,
        top_products=top_products,
        by_category=by_category,
        inv_value=inv_value,
        brands=brands,
        movements=movements,
        date_from=date_from_str,
        date_to=date_to_str,
        group_by=group_by,
    )


# ── JSON API for Chart.js ─────────────────────────────────────────────────────

@analytics_bp.route("/api/revenue")
@login_required
@permission_required("analytics", "read")
def api_revenue():
    db = get_db()
    now = utcnow()
    date_from = start_of_day(
        parse_date(request.args.get("date_from", "")) or now - datetime.timedelta(days=29)
    )
    date_to = end_of_day(
        parse_date(request.args.get("date_to", "")) or now
    )
    group_by = request.args.get("group_by", "day")
    return jsonify(sales_over_time(db, date_from, date_to, group_by))


@analytics_bp.route("/api/inventory-value")
@login_required
@permission_required("analytics", "read")
def api_inventory_value():
    db = get_db()
    return jsonify(_inventory_value(db))


@analytics_bp.route("/api/top-products")
@login_required
@permission_required("analytics", "read")
def api_top_products():
    db = get_db()
    limit = safe_int(request.args.get("limit", 10))
    return jsonify(_top_selling_products(db, limit=limit))
