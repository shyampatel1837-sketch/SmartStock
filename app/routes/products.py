"""SmartStock – Product Routes"""
from flask import (Blueprint, request, render_template, redirect, url_for,
                   flash, jsonify, g)
from ..db import get_db
from ..services.product_service import (
    create_product, get_product_by_id, list_products,
    search_products, update_product, deactivate_product, delete_product,
    get_low_stock_products,
)
from ..validators.product_validator import validate_product
from ..validators.base import validate_positive_decimal
from ..models.product import CATEGORIES
from ..utils import safe_int
from .decorators import login_required, permission_required

products_bp = Blueprint("products", __name__)


@products_bp.route("/")
@login_required
@permission_required("products", "read")
def index():
    db = get_db()
    filters = {
        "category": request.args.get("category"),
        "brand": request.args.get("brand"),
        "status": request.args.get("status", "active"),
        "min_price": request.args.get("min_price"),
        "max_price": request.args.get("max_price"),
        "low_stock": request.args.get("low_stock") == "1",
    }
    for field in ("min_price", "max_price"):
        value = filters[field]
        if value not in (None, ""):
            error = validate_positive_decimal(value, field.replace("_", " ").title(), allow_zero=True)
            if error:
                flash(error, "error")
                filters[field] = None
    if filters["min_price"] and filters["max_price"]:
        from decimal import Decimal
        if Decimal(filters["min_price"]) > Decimal(filters["max_price"]):
            flash("Minimum price cannot exceed maximum price.", "error")
            filters["min_price"] = filters["max_price"] = None
    page = safe_int(request.args.get("page", 1))
    sort_by = request.args.get("sort", "name")
    result = list_products(db, filters, page=page, sort_by=sort_by)
    # Get distinct brands for filter
    brands = db.products.distinct("brand", {"status": {"$ne": "discontinued"}})
    return render_template(
        "products/index.html",
        products=result["items"],
        pagination=result["pagination"],
        filters=filters,
        categories=CATEGORIES,
        brands=sorted(brands),
        sort_by=sort_by,
    )


@products_bp.route("/search")
@login_required
@permission_required("products", "read")
def search():
    db = get_db()
    q = request.args.get("q", "").strip()
    products = search_products(db, q) if q else []
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(products)
    return render_template("products/search.html", products=products, query=q)


@products_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required("products", "write")
def new():
    db = get_db()
    suppliers = list(db.suppliers.find({"status": "active"}, {"name": 1}).sort("name", 1))
    if request.method == "POST":
        data = request.form.to_dict()
        errors = validate_product(data)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("products/form.html", data=data,
                                   categories=CATEGORIES, suppliers=suppliers)
        try:
            product = create_product(db, data)
            flash(f"Product '{product['name']}' created with SKU {product['sku']}.", "success")
            return redirect(url_for("products.show", product_id=product["_id"]))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("products/form.html", data={},
                           categories=CATEGORIES, suppliers=suppliers)


@products_bp.route("/<product_id>")
@login_required
@permission_required("products", "read")
def show(product_id):
    db = get_db()
    product = get_product_by_id(db, product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("products.index"))
    # Recent movements for this product
    from ..services.inventory_service import get_stock_movements
    movements = get_stock_movements(db, product_id=product_id, per_page=10)
    # Rating summary
    from ..services.review_service import get_product_rating_summary, get_product_reviews
    rating = get_product_rating_summary(db, product_id)
    reviews = get_product_reviews(db, product_id, per_page=5)
    return render_template("products/show.html", product=product,
                           movements=movements["items"], rating=rating,
                           reviews=reviews["items"])


@products_bp.route("/<product_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("products", "write")
def edit(product_id):
    db = get_db()
    product = get_product_by_id(db, product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("products.index"))
    suppliers = list(db.suppliers.find({"status": "active"}, {"name": 1}).sort("name", 1))
    if request.method == "POST":
        data = request.form.to_dict()
        errors = validate_product(data, is_update=True)
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("products/form.html", data=data, product=product,
                                   categories=CATEGORIES, suppliers=suppliers, is_edit=True)
        try:
            updated = update_product(db, product_id, data)
            flash(f"Product '{updated['name']}' updated.", "success")
            return redirect(url_for("products.show", product_id=product_id))
        except ValueError as e:
            flash(str(e), "error")
    return render_template("products/form.html", data=product, product=product,
                           categories=CATEGORIES, suppliers=suppliers, is_edit=True)


@products_bp.route("/<product_id>/deactivate", methods=["POST"])
@login_required
@permission_required("products", "write")
def deactivate(product_id):
    db = get_db()
    changed = deactivate_product(db, product_id)
    flash(
        "Product deactivated." if changed else "Product not found or already inactive.",
        "info" if changed else "error",
    )
    return redirect(url_for("products.index"))


@products_bp.route("/<product_id>/delete", methods=["POST"])
@login_required
@permission_required("products", "delete")
def delete(product_id):
    db = get_db()
    result = delete_product(db, product_id)
    flash(result["reason"], "success" if result["deleted"] else "error")
    return redirect(url_for("products.index"))


@products_bp.route("/low-stock")
@login_required
@permission_required("products", "read")
def low_stock():
    db = get_db()
    products = get_low_stock_products(db)
    return render_template("products/low_stock.html", products=products)


# ── API endpoints (used by frontend JS) ──────────────────────────────────────

@products_bp.route("/api/search")
@login_required
@permission_required("products", "read")
def api_search():
    db = get_db()
    q = request.args.get("q", "").strip()
    results = search_products(db, q, limit=15)
    return jsonify(results)


@products_bp.route("/api/<product_id>")
@login_required
@permission_required("products", "read")
def api_get(product_id):
    db = get_db()
    product = get_product_by_id(db, product_id)
    if not product:
        return jsonify({"error": "Not found"}), 404
    return jsonify(product)
