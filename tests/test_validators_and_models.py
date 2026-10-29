from bson import Decimal128, ObjectId
from decimal import Decimal

from app.models.product import build_product_document
from app.models.review import build_review_document
from app.models.sale import build_sale_document
from app.validators.product_validator import validate_product
from app.validators.purchase_validator import validate_purchase_order
from app.validators.sale_validator import validate_sale
from app.models.user import has_permission


def test_product_validation_and_category_specifications():
    data = {
        "sku": "lap-001",
        "name": "Laptop",
        "category": "Laptops",
        "purchase_cost": "500.00",
        "selling_price": "750.00",
        "cpu": "Example CPU",
        "ram_gb": "16",
    }
    assert validate_product(data) == []
    product = build_product_document(data)
    assert product["sku"] == "LAP-001"
    assert product["specs"] == {"ram_gb": "16", "cpu": "Example CPU"}
    assert isinstance(product["purchase_cost"], Decimal128)

    phone = build_product_document({
        **data,
        "category": "Smartphones",
        "camera_mp": "48",
    })
    assert phone["specs"]["camera_mp"] == "48"
    assert "cpu" not in phone["specs"]


def test_product_rejects_unknown_category_and_non_finite_price():
    errors = validate_product({
        "sku": "SKU-1",
        "name": "Product",
        "category": "Unknown",
        "purchase_cost": "NaN",
        "selling_price": "10",
    })
    assert any("category" in error.lower() for error in errors)
    assert any("finite" in error.lower() for error in errors)


def test_sale_validation_rejects_zero_quantity():
    errors = validate_sale({
        "payment_method": "cash",
        "items": [{
            "product_id": str(ObjectId()),
            "quantity": "0",
            "unit_price": "10.00",
        }],
    })
    assert any("quantity" in error.lower() for error in errors)


def test_sale_validation_rejects_over_discount_and_fractional_quantity():
    errors = validate_sale({
        "payment_method": "cash",
        "discount_amount": "25",
        "items": [{
            "product_id": str(ObjectId()),
            "quantity": 1.5,
            "unit_price": "10",
        }],
    })
    assert any("whole number" in error.lower() for error in errors)
    assert any("discount" in error.lower() for error in errors)


def test_sale_totals_use_decimal128():
    sale = build_sale_document({
        "payment_method": "cash",
        "items": [{
            "product_id": str(ObjectId()),
            "quantity": 2,
            "unit_price": "100.00",
        }],
    }, "INV-TEST-1", tax_percent=18)
    assert sale["total_amount"].to_decimal() == Decimal("236.00")


def test_purchase_order_requires_valid_product_quantities_and_prices():
    errors = validate_purchase_order({
        "supplier_id": str(ObjectId()),
        "items": [{
            "product_id": "not-an-object-id",
            "quantity": 0,
            "unit_price": "-1",
        }],
    })
    assert any("product" in error.lower() for error in errors)
    assert any("quantity" in error.lower() for error in errors)
    assert any("unit price" in error.lower() for error in errors)


def test_review_model_rejects_out_of_range_rating():
    try:
        build_review_document({"product_id": str(ObjectId()), "rating": 6})
    except ValueError as exc:
        assert "between 1 and 5" in str(exc)
    else:
        raise AssertionError("Invalid review rating was accepted")


def test_role_permissions_match_access_policy():
    assert has_permission("sales", "sales", "write")
    assert not has_permission("sales", "analytics", "read")
    assert has_permission("inventory", "purchases", "write")
    assert not has_permission("inventory", "sales", "read")
    assert not has_permission("inventory", "sales", "write")
