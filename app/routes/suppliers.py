"""SmartStock – Supplier Routes"""
from flask import (Blueprint, request, render_template, redirect,
                   url_for, flash, jsonify, g)
from ..db import get_db
from ..services.supplier_service import (
    create_supplier, get_supplier, list_suppliers, update_supplier, delete_supplier
)
from ..validators.supplier_validator import validate_supplier
from ..utils import safe_int
from .decorators import login_required, permission_required

suppliers_bp = Blueprint("suppliers", __name__)


@suppliers_bp.route("/")
@login_required
def index():
    db = get_db()
    status = request.args.get("status", "active")
    page = safe_int(request.args.get("page", 1))
    result = list_suppliers(db, status=status, page=page)
    return render_template("suppliers/index.html",
                           suppliers=result["items"],
                           pagination=result["pagination"],
                           status_filter=status)


@suppliers_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required("suppliers", "write")
def new():
    db = get_db()
    if request.method == "POST":
        data = request.form.to_dict()
        errors = validate_supplier(data)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("suppliers/form.html", data=data)
        try:
            supplier = create_supplier(db, data)
            flash(f"Supplier '{supplier['name']}' added.", "success")
            return redirect(url_for("suppliers.show", supplier_id=supplier["_id"]))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("suppliers/form.html", data={})


@suppliers_bp.route("/<supplier_id>")
@login_required
def show(supplier_id):
    db = get_db()
    supplier = get_supplier(db, supplier_id)
    if not supplier:
        flash("Supplier not found.", "error")
        return redirect(url_for("suppliers.index"))
    from ..services.purchase_service import list_purchase_orders
    orders = list_purchase_orders(db, supplier_id=supplier_id, per_page=10)
    return render_template("suppliers/show.html", supplier=supplier,
                           orders=orders["items"])


@suppliers_bp.route("/<supplier_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("suppliers", "write")
def edit(supplier_id):
    db = get_db()
    supplier = get_supplier(db, supplier_id)
    if not supplier:
        flash("Supplier not found.", "error")
        return redirect(url_for("suppliers.index"))
    if request.method == "POST":
        data = request.form.to_dict()
        errors = validate_supplier(data, is_update=True)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("suppliers/form.html", data=data,
                                   supplier=supplier, is_edit=True)
        try:
            updated = update_supplier(db, supplier_id, data)
            flash(f"Supplier '{updated['name']}' updated.", "success")
            return redirect(url_for("suppliers.show", supplier_id=supplier_id))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("suppliers/form.html", data=supplier,
                           supplier=supplier, is_edit=True)


@suppliers_bp.route("/<supplier_id>/delete", methods=["POST"])
@login_required
@permission_required("suppliers", "delete")
def delete(supplier_id):
    db = get_db()
    result = delete_supplier(db, supplier_id)
    flash(result["reason"], "success" if result["deleted"] else "error")
    return redirect(url_for("suppliers.index"))


@suppliers_bp.route("/api/list")
@login_required
def api_list():
    db = get_db()
    suppliers = list(db.suppliers.find({"status": "active"}, {"name": 1}).sort("name", 1))
    from ..utils import mongo_doc_to_dict
    return jsonify([mongo_doc_to_dict(s) for s in suppliers])
