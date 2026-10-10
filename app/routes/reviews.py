"""SmartStock – Reviews Routes"""
from flask import (Blueprint, request, render_template, redirect,
                   url_for, flash, jsonify, g)
from ..db import get_db
from ..services.review_service import (
    create_review, get_product_reviews, moderate_review, get_pending_reviews
)
from ..utils import safe_int, mongo_doc_to_dict
from .decorators import login_required, permission_required

reviews_bp = Blueprint("reviews", __name__)


@reviews_bp.route("/")
@login_required
def index():
    db = get_db()
    pending = get_pending_reviews(db)
    return render_template("reviews/index.html", pending=pending)


@reviews_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required("reviews", "write")
def new():
    db = get_db()
    product_id = request.args.get("product_id") or request.form.get("product_id")
    product = None
    if product_id:
        from ..services.product_service import get_product_by_id
        product = get_product_by_id(db, product_id)
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            review = create_review(db, data)
            flash("Review submitted for moderation.", "success")
            return redirect(url_for("products.show", product_id=data["product_id"]))
        except (ValueError, Exception) as e:
            flash(str(e), "error")
    return render_template("reviews/form.html", product=product)


@reviews_bp.route("/<review_id>/approve", methods=["POST"])
@login_required
@permission_required("reviews", "moderate")
def approve(review_id):
    db = get_db()
    moderate_review(db, review_id, "approved")
    flash("Review approved.", "success")
    return redirect(url_for("reviews.index"))


@reviews_bp.route("/<review_id>/reject", methods=["POST"])
@login_required
@permission_required("reviews", "moderate")
def reject(review_id):
    db = get_db()
    moderate_review(db, review_id, "rejected")
    flash("Review rejected.", "info")
    return redirect(url_for("reviews.index"))


@reviews_bp.route("/api/product/<product_id>")
@login_required
def api_product_reviews(product_id):
    db = get_db()
    page = safe_int(request.args.get("page", 1))
    result = get_product_reviews(db, product_id, page=page)
    return jsonify(result)
