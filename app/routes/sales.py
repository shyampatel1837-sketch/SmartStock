"""SmartStock – Sales Routes"""
import json
from flask import (Blueprint, request, render_template, redirect,
                   url_for, flash, jsonify, g)
from ..db import get_db
from ..services.sale_service import (
    create_sale, get_sale, list_sales, void_sale, get_sale_by_invoice
)
from ..validators.sale_validator import validate_sale
from ..utils import safe_int
from .decorators import login_required, permission_required

sales_bp = Blueprint("sales", __name__)


@sales_bp.route("/")
@login_required
def index():
    db = get_db()
    filters = {
        "status": request.args.get("status"),
        "payment_method": request.args.get("payment_method"),
    }
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    from ..utils import parse_date, start_of_day, end_of_day
    if date_from:
        filters["date_from"] = start_of_day(parse_date(date_from))
    if date_to:
        filters["date_to"] = end_of_day(parse_date(date_to))

    page = safe_int(request.args.get("page", 1))
    result = list_sales(db, filters=filters, page=page)
    return render_template("sales/index.html",
                           sales=result["items"],
                           pagination=result["pagination"],
                           filters=request.args)


@sales_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required("sales", "write")
def new():
    if request.method == "POST":
        db = get_db()
        data = request.form.to_dict()
        items_raw = request.form.get("items_json", "[]")
        try:
            data["items"] = json.loads(items_raw)
        except (json.JSONDecodeError, ValueError):
            flash("Invalid items data.", "error")
            return render_template("sales/form.html")
        errors = validate_sale(data)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("sales/form.html")
        actor = g.current_user.get("_id") if g.current_user else None
        try:
            sale = create_sale(db, data, actor=actor)
            flash(f"Sale {sale['invoice_number']} completed.", "success")
            return redirect(url_for("sales.invoice", sale_id=sale["_id"]))
        except (ValueError, RuntimeError) as e:
            flash(str(e), "error")
    return render_template("sales/form.html")


@sales_bp.route("/<sale_id>")
@login_required
def show(sale_id):
    db = get_db()
    sale = get_sale(db, sale_id)
    if not sale:
        flash("Sale not found.", "error")
        return redirect(url_for("sales.index"))
    return render_template("sales/show.html", sale=sale)


@sales_bp.route("/<sale_id>/invoice")
@login_required
def invoice(sale_id):
    db = get_db()
    sale = get_sale(db, sale_id)
    if not sale:
        flash("Sale not found.", "error")
        return redirect(url_for("sales.index"))
    return render_template("sales/invoice.html", sale=sale)


@sales_bp.route("/<sale_id>/void", methods=["POST"])
@login_required
@permission_required("sales", "void")
def void(sale_id):
    db = get_db()
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("A reason is required to void a sale.", "error")
        return redirect(url_for("sales.show", sale_id=sale_id))
    actor = g.current_user.get("_id") if g.current_user else None
    result = void_sale(db, sale_id, reason, actor=actor)
    flash(
        f"Sale {result.get('invoice_number', '')} voided." if result["success"] else result["error"],
        "success" if result["success"] else "error",
    )
    return redirect(url_for("sales.show", sale_id=sale_id))


# ── API ───────────────────────────────────────────────────────────────────────

@sales_bp.route("/api/new", methods=["POST"])
@login_required
@permission_required("sales", "write")
def api_new():
    """JSON endpoint for the POS form."""
    db = get_db()
    data = request.get_json(force=True, silent=True) or {}
    errors = validate_sale(data)
    if errors:
        return jsonify({"success": False, "errors": errors}), 400
    actor = g.current_user.get("_id") if g.current_user else None
    try:
        sale = create_sale(db, data, actor=actor)
        return jsonify({"success": True, "sale": sale})
    except (ValueError, RuntimeError) as e:
        return jsonify({"success": False, "error": str(e)}), 422
