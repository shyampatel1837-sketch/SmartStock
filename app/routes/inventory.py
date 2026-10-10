"""SmartStock – Inventory & Stock Adjustment Routes"""
from flask import (Blueprint, request, render_template, redirect,
                   url_for, flash, jsonify, g)
from ..db import get_db
from ..services.inventory_service import (
    adjust_stock, record_damage, get_stock_movements
)
from ..utils import safe_int, mongo_doc_to_dict
from ..models.stock_movement import MOVEMENT_TYPES
from .decorators import login_required, permission_required

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.route("/")
@login_required
def index():
    db = get_db()
    product_id = request.args.get("product_id")
    movement_type = request.args.get("movement_type")
    page = safe_int(request.args.get("page", 1))
    result = get_stock_movements(db, product_id=product_id,
                                  movement_type=movement_type, page=page)
    return render_template("inventory/index.html",
                           movements=result["items"],
                           pagination=result["pagination"],
                           movement_types=MOVEMENT_TYPES,
                           current_product=product_id,
                           current_type=movement_type)


@inventory_bp.route("/adjust", methods=["GET", "POST"])
@login_required
@permission_required("inventory", "write")
def adjust():
    db = get_db()
    if request.method == "POST":
        product_id = request.form.get("product_id")
        try:
            qty_change = int(request.form.get("quantity_change", 0))
        except ValueError:
            flash("Quantity must be a whole number.", "error")
            return redirect(url_for("inventory.adjust"))
        reason = request.form.get("reason", "").strip()
        actor = g.current_user.get("_id") if g.current_user else None
        result = adjust_stock(db, product_id, qty_change, reason, actor=actor)
        flash(
            f"Stock updated. New quantity: {result.get('new_stock_qty')}"
            if result["success"] else result["error"],
            "success" if result["success"] else "error",
        )
        if result["success"]:
            return redirect(url_for("products.show", product_id=product_id))
    product_id = request.args.get("product_id")
    product = None
    if product_id:
        from ..services.product_service import get_product_by_id
        product = get_product_by_id(db, product_id)
    return render_template("inventory/adjust.html", product=product)


@inventory_bp.route("/damage", methods=["GET", "POST"])
@login_required
@permission_required("inventory", "write")
def damage():
    db = get_db()
    if request.method == "POST":
        product_id = request.form.get("product_id")
        try:
            qty = int(request.form.get("quantity", 0))
        except ValueError:
            flash("Quantity must be a whole number.", "error")
            return redirect(url_for("inventory.damage"))
        reason = request.form.get("reason", "").strip()
        actor = g.current_user.get("_id") if g.current_user else None
        result = record_damage(db, product_id, qty, reason, actor=actor)
        flash("Damage recorded." if result["success"] else result["error"],
              "success" if result["success"] else "error")
        if result["success"]:
            return redirect(url_for("products.show", product_id=product_id))
    return render_template("inventory/damage.html")


# ── API ───────────────────────────────────────────────────────────────────────

@inventory_bp.route("/api/movements")
@login_required
def api_movements():
    db = get_db()
    product_id = request.args.get("product_id")
    page = safe_int(request.args.get("page", 1))
    result = get_stock_movements(db, product_id=product_id, page=page)
    return jsonify(result)
