"""SmartStock – Purchase Order Routes"""
import json
from flask import (Blueprint, request, render_template, redirect,
                   url_for, flash, jsonify, g)
from ..db import get_db
from ..services.purchase_service import (
    create_purchase_order, get_purchase_order, list_purchase_orders,
    receive_purchase_order, cancel_purchase_order,
)
from ..utils import safe_int, mongo_doc_to_dict
from .decorators import login_required, permission_required

purchases_bp = Blueprint("purchases", __name__)


@purchases_bp.route("/")
@login_required
@permission_required("purchases", "read")
def index():
    db = get_db()
    status = request.args.get("status")
    supplier_id = request.args.get("supplier_id")
    page = safe_int(request.args.get("page", 1))
    result = list_purchase_orders(db, supplier_id=supplier_id,
                                  status=status, page=page)
    suppliers = list(db.suppliers.find({"status": "active"}, {"name": 1}).sort("name", 1))
    return render_template("purchases/index.html",
                           orders=result["items"],
                           pagination=result["pagination"],
                           suppliers=[mongo_doc_to_dict(s) for s in suppliers],
                           status_filter=status)


@purchases_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required("purchases", "write")
def new():
    db = get_db()
    suppliers = list(db.suppliers.find({"status": "active"}, {"name": 1}).sort("name", 1))
    products = list(db.products.find(
        {"status": {"$ne": "discontinued"}},
        {"name": 1, "sku": 1, "purchase_cost": 1},
    ).sort("name", 1))
    products = [mongo_doc_to_dict(product) for product in products]
    if request.method == "POST":
        data = request.form.to_dict()
        # Items come as JSON from the frontend
        items_raw = request.form.get("items_json", "[]")
        try:
            data["items"] = json.loads(items_raw)
        except (json.JSONDecodeError, ValueError):
            flash("Invalid items data.", "error")
            return render_template("purchases/form.html",
                                   suppliers=[mongo_doc_to_dict(s) for s in suppliers],
                                   products=products)
        if not data["items"]:
            flash("At least one item is required.", "error")
            return render_template("purchases/form.html",
                                   suppliers=[mongo_doc_to_dict(s) for s in suppliers],
                                   products=products)
        if not data.get("supplier_id"):
            flash("Please select a supplier.", "error")
            return render_template("purchases/form.html",
                                   suppliers=[mongo_doc_to_dict(s) for s in suppliers],
                                   products=products)
        try:
            po = create_purchase_order(db, data)
            flash(f"Purchase order {po['reference']} created.", "success")
            return redirect(url_for("purchases.show", po_id=po["_id"]))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("purchases/form.html",
                           suppliers=[mongo_doc_to_dict(s) for s in suppliers],
                           products=products)


@purchases_bp.route("/<po_id>")
@login_required
@permission_required("purchases", "read")
def show(po_id):
    db = get_db()
    po = get_purchase_order(db, po_id)
    if not po:
        flash("Purchase order not found.", "error")
        return redirect(url_for("purchases.index"))
    # Fetch supplier name
    from bson import ObjectId
    if po.get("supplier_id") and ObjectId.is_valid(po["supplier_id"]):
        supplier = db.suppliers.find_one({"_id": ObjectId(po["supplier_id"])}, {"name": 1})
        po["supplier_name"] = supplier.get("name", "Unknown") if supplier else "Unknown"
    return render_template("purchases/show.html", po=po)


@purchases_bp.route("/<po_id>/receive", methods=["POST"])
@login_required
@permission_required("purchases", "write")
def receive(po_id):
    db = get_db()
    actor = g.current_user.get("_id") if g.current_user else None
    result = receive_purchase_order(db, po_id, actor=actor)
    if result["success"]:
        flash(f"Stock received for {result['reference']}. "
              f"{result['items_received']} product(s) updated.", "success")
    else:
        flash(result["error"], "error")
    return redirect(url_for("purchases.show", po_id=po_id))


@purchases_bp.route("/<po_id>/cancel", methods=["POST"])
@login_required
@permission_required("purchases", "write")
def cancel(po_id):
    db = get_db()
    reason = request.form.get("reason", "")
    result = cancel_purchase_order(db, po_id, reason)
    flash("Purchase order cancelled." if result["success"] else result["error"],
          "success" if result["success"] else "error")
    return redirect(url_for("purchases.show", po_id=po_id))
