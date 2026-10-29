"""Opt-in integration coverage against an isolated local MongoDB database."""
from __future__ import annotations

import datetime
import math
import os
import uuid

import pytest
from bson import ObjectId
from pymongo.uri_parser import parse_uri

from app import create_app
from app.config import get_config
from app.models.purchase_order import build_po_document
from app.models.supplier import build_supplier_document
from app.services.analytics_service import (
    _inventory_value,
    _revenue_by_category,
    _top_selling_products,
    _top_rated_products,
    get_dashboard_summary,
    sales_over_time,
)
from app.services.inventory_service import adjust_stock
from app.services.product_service import create_product
from app.services.purchase_service import receive_purchase_order
from app.services.review_service import (
    create_review,
    get_product_rating_summary,
    moderate_review,
)
from app.services.sale_service import create_sale, void_sale


pytestmark = pytest.mark.skipif(
    os.environ.get("SMARTSTOCK_RUN_MONGO_INTEGRATION") != "1",
    reason="Set SMARTSTOCK_RUN_MONGO_INTEGRATION=1 to enable local MongoDB tests.",
)

TEST_DATABASE = "smartstock_test"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _require_local_test_database() -> None:
    config = get_config("testing")
    uri = config.MONGO_URI
    if not uri.startswith("mongodb://"):
        pytest.fail("Integration tests require a direct local mongodb:// URI.")

    parsed_uri = parse_uri(uri)
    hosts = {host.lower().strip("[]") for host, _port in parsed_uri["nodelist"]}
    if not hosts or not hosts.issubset(LOCAL_HOSTS):
        pytest.fail(
            "Integration tests may connect only to localhost, 127.0.0.1, or ::1."
        )
    if config.MONGO_DB_NAME != TEST_DATABASE:
        pytest.fail(
            f"Integration tests require the {TEST_DATABASE!r} database; "
            f"configuration selected {config.MONGO_DB_NAME!r}."
        )


@pytest.fixture
def local_mongo():
    _require_local_test_database()
    app = create_app("testing")
    client = app.extensions.get("mongo_client")
    if client is None:
        pytest.fail("Local MongoDB did not connect; integration tests cannot run.")

    database = client[TEST_DATABASE]
    resources = {
        "product_ids": [],
        "supplier_ids": [],
        "purchase_order_ids": [],
        "sale_ids": [],
        "review_ids": [],
        "counter_ids": [],
    }

    try:
        client.admin.command("ping")
        yield app, database, resources
    finally:
        if resources["sale_ids"]:
            database.sales.delete_many({"_id": {"$in": resources["sale_ids"]}})
            assert database.sales.count_documents({
                "_id": {"$in": resources["sale_ids"]}
            }) == 0
        if resources["review_ids"]:
            database.reviews.delete_many({"_id": {"$in": resources["review_ids"]}})
            assert database.reviews.count_documents({
                "_id": {"$in": resources["review_ids"]}
            }) == 0
        if resources["purchase_order_ids"]:
            database.purchase_orders.delete_many({
                "_id": {"$in": resources["purchase_order_ids"]}
            })
            assert database.purchase_orders.count_documents({
                "_id": {"$in": resources["purchase_order_ids"]}
            }) == 0
        if resources["product_ids"]:
            database.stock_movements.delete_many({
                "product_id": {"$in": resources["product_ids"]}
            })
            assert database.stock_movements.count_documents({
                "product_id": {"$in": resources["product_ids"]}
            }) == 0
            database.products.delete_many({"_id": {"$in": resources["product_ids"]}})
            assert database.products.count_documents({
                "_id": {"$in": resources["product_ids"]}
            }) == 0
        if resources["supplier_ids"]:
            database.suppliers.delete_many({"_id": {"$in": resources["supplier_ids"]}})
            assert database.suppliers.count_documents({
                "_id": {"$in": resources["supplier_ids"]}
            }) == 0
        if resources["counter_ids"]:
            database.counters.delete_many({"_id": {"$in": resources["counter_ids"]}})
            assert database.counters.count_documents({
                "_id": {"$in": resources["counter_ids"]}
            }) == 0
        client.close()


def _category_total(rows: list[dict], category: str, field: str) -> float:
    return float(next(
        (row.get(field, 0) for row in rows if row.get("category") == category),
        0,
    ))


def test_local_mongodb_inventory_purchasing_sales_reviews_and_analytics(local_mongo):
    app, db, resources = local_mongo
    token = uuid.uuid4().hex
    sku = f"IT-{token[:20]}".upper()
    invoice_prefix = f"IT{token[:12]}".upper()
    counter_id = f"{invoice_prefix}-{datetime.datetime.utcnow():%Y%m}"
    assert db.counters.find_one({"_id": counter_id}) is None
    resources["counter_ids"].append(counter_id)
    actor = ObjectId()

    with app.app_context():
        app.config["STORE_INVOICE_PREFIX"] = invoice_prefix

        inventory_before = _inventory_value(db)
        time_from = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        time_to = datetime.datetime.utcnow() + datetime.timedelta(days=1)
        category_sales_before = _revenue_by_category(
            db, time_from, time_to,
        )
        sales_before = sales_over_time(db, time_from, time_to)
        dashboard_before = get_dashboard_summary(db)

        product = create_product(db, {
            "sku": sku,
            "name": f"Integration Product {token[:10]}",
            "category": "Accessories",
            "brand": f"Integration {token[:8]}",
            "purchase_cost": "5.00",
            "selling_price": "10.00",
            "stock_qty": 3,
            "reorder_threshold": 1,
        })
        product_id = ObjectId(product["_id"])
        resources["product_ids"].append(product_id)
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 3
        dashboard_after_create = get_dashboard_summary(db)
        assert (
            dashboard_after_create["products"]["total_products"]
            == dashboard_before["products"]["total_products"] + 1
        )
        assert (
            dashboard_after_create["products"]["total_stock_units"]
            == dashboard_before["products"]["total_stock_units"] + 3
        )
        opening = db.stock_movements.find_one({
            "product_id": product_id,
            "movement_type": "opening_stock",
        })
        assert opening["quantity_change"] == 3

        adjustment = adjust_stock(db, str(product_id), 2, "Integration stock increase")
        assert adjustment["success"] is True
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 5
        assert db.stock_movements.count_documents({
            "product_id": product_id,
            "movement_type": "adjustment_up",
            "quantity_change": 2,
        }) == 1

        supplier_id = ObjectId()
        resources["supplier_ids"].append(supplier_id)
        supplier = build_supplier_document({
            "name": f"Integration supplier {token}",
            "status": "active",
        })
        supplier["_id"] = supplier_id
        db.suppliers.insert_one(supplier)

        po_id = ObjectId()
        resources["purchase_order_ids"].append(po_id)
        po = build_po_document({
            "supplier_id": str(supplier_id),
            "items": [{
                "product_id": str(product_id),
                "product_name": product["name"],
                "product_sku": sku,
                "quantity": 4,
                "unit_price": "4.25",
            }],
        }, reference=f"IT-PO-{token}")
        po["_id"] = po_id
        db.purchase_orders.insert_one(po)

        receipt = receive_purchase_order(db, str(po_id), actor=actor)
        assert receipt["success"] is True
        assert db.purchase_orders.find_one({"_id": po_id})["status"] == "received"
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 9
        assert db.stock_movements.count_documents({
            "product_id": product_id,
            "reference_id": po_id,
            "reference_type": "purchase_order",
            "movement_type": "purchase_receipt",
            "quantity_change": 4,
        }) == 1

        repeated_receipt = receive_purchase_order(db, str(po_id), actor=actor)
        assert repeated_receipt["success"] is False
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 9
        assert db.stock_movements.count_documents({
            "product_id": product_id,
            "reference_id": po_id,
            "reference_type": "purchase_order",
        }) == 1

        inventory_after_receipt = _inventory_value(db)
        assert math.isclose(
            _category_total(inventory_after_receipt["by_category"], "Accessories", "total_value")
            - _category_total(inventory_before["by_category"], "Accessories", "total_value"),
            38.25,
            abs_tol=0.01,
        )

        sale_data = {
            "payment_method": "cash",
            "idempotency_key": f"it-{token}",
            "items": [{
                "product_id": str(product_id),
                "quantity": 3,
                "unit_price": "9999.99",
            }],
        }
        sale = create_sale(db, sale_data, actor=actor)
        sale_id = ObjectId(sale["_id"])
        resources["sale_ids"].append(sale_id)
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 6
        assert db.sales.find_one({"_id": sale_id})["items"][0]["unit_price"].to_decimal() == 10
        assert db.stock_movements.count_documents({
            "product_id": product_id,
            "reference_id": sale_id,
            "reference_type": "sale",
            "movement_type": "sale",
            "quantity_change": -3,
        }) == 1

        same_sale = create_sale(db, sale_data, actor=actor)
        assert same_sale["_id"] == str(sale_id)
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 6
        assert db.stock_movements.count_documents({
            "product_id": product_id,
            "reference_id": sale_id,
            "reference_type": "sale",
        }) == 1

        current_sales = sales_over_time(db, time_from, time_to)
        assert sum(row["count"] for row in current_sales) == (
            sum(row["count"] for row in sales_before) + 1
        )
        assert math.isclose(
            sum(row["revenue"] for row in current_sales)
            - sum(row["revenue"] for row in sales_before),
            35.40,
            abs_tol=0.01,
        )
        top_products = _top_selling_products(
            db, limit=10000, date_from=time_from, date_to=time_to
        )
        own_top_product = next(row for row in top_products if row["product_sku"] == sku)
        assert own_top_product["units_sold"] == 3
        category_sales_after = _revenue_by_category(db, time_from, time_to)
        assert math.isclose(
            _category_total(category_sales_after, "Accessories", "revenue")
            - _category_total(category_sales_before, "Accessories", "revenue"),
            30.00,
            abs_tol=0.01,
        )
        dashboard_after_sale = get_dashboard_summary(db)
        assert "top_products" in dashboard_after_sale

        for rating in (4, 5, 3):
            review = create_review(db, {
                "product_id": str(product_id),
                "rating": rating,
                "title": f"Integration review {rating}",
                "body": "Created by the isolated MongoDB integration test.",
                "reviewer_name": "Integration test",
            })
            review_id = ObjectId(review["_id"])
            resources["review_ids"].append(review_id)
            assert moderate_review(db, str(review_id), "approved") is True

        rating_summary = get_product_rating_summary(db, str(product_id))
        assert rating_summary == {
            "average_rating": 4.0,
            "review_count": 3,
            "distribution": {"1": 0, "2": 0, "3": 1, "4": 1, "5": 1},
        }
        dashboard_after_reviews = get_dashboard_summary(db)
        top_rated = _top_rated_products(db, min_reviews=3, limit=10000)
        assert any(
            row["product_sku"] == sku and row["review_count"] == 3
            for row in top_rated
        )
        assert "avg_ratings" in dashboard_after_reviews

        voided = void_sale(db, str(sale_id), "Integration test void", actor=actor)
        assert voided["success"] is True
        assert db.sales.find_one({"_id": sale_id})["status"] == "voided"
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 9
        assert db.stock_movements.count_documents({
            "product_id": product_id,
            "reference_id": sale_id,
            "reference_type": "sale_void",
            "movement_type": "return_customer",
            "quantity_change": 3,
        }) == 1
        repeated_void = void_sale(db, str(sale_id), "Repeated integration void", actor=actor)
        assert repeated_void["success"] is False
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 9
        assert db.stock_movements.count_documents({
            "product_id": product_id,
            "reference_id": sale_id,
            "reference_type": "sale_void",
        }) == 1

        reduced = adjust_stock(db, str(product_id), -9, "Integration insufficient-stock check")
        assert reduced["success"] is True
        movements_before_failed_sale = db.stock_movements.count_documents({
            "product_id": product_id,
        })
        with pytest.raises(ValueError, match="insufficient stock"):
            create_sale(db, {
                "payment_method": "cash",
                "idempotency_key": f"insufficient-{token}",
                "items": [{
                    "product_id": str(product_id),
                    "quantity": 1,
                    "unit_price": "10.00",
                }],
            }, actor=actor)
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 0
        assert db.stock_movements.count_documents({
            "product_id": product_id,
        }) == movements_before_failed_sale

        adjust_stock(db, str(product_id), 1, "Integration partial-sale rollback check")
        movements_before_partial_failure = db.stock_movements.count_documents({
            "product_id": product_id,
        })
        with pytest.raises(ValueError, match="insufficient stock"):
            create_sale(db, {
                "payment_method": "cash",
                "idempotency_key": f"partial-insufficient-{token}",
                "items": [
                    {
                        "product_id": str(product_id),
                        "quantity": 1,
                        "unit_price": "10.00",
                    },
                    {
                        "product_id": str(product_id),
                        "quantity": 1,
                        "unit_price": "10.00",
                    },
                ],
            }, actor=actor)
        assert db.products.find_one({"_id": product_id})["stock_qty"] == 1
        assert db.stock_movements.count_documents({
            "product_id": product_id,
        }) == movements_before_partial_failure
        adjust_stock(db, str(product_id), -1, "Restore integration stock level")

        restored = adjust_stock(db, str(product_id), 2, "Integration duplicate-invoice check")
        assert restored["success"] is True
        counter = db.counters.find_one({"_id": counter_id})
        next_invoice = f"{invoice_prefix}-{datetime.datetime.utcnow():%Y%m}-{counter['seq'] + 1:06d}"
        collision_id = ObjectId()
        resources["sale_ids"].append(collision_id)
        db.sales.insert_one({
            "_id": collision_id,
            "invoice_number": next_invoice,
            "status": "reserved_for_integration_test",
        })
        stock_before_duplicate_invoice = db.products.find_one({"_id": product_id})["stock_qty"]
        movements_before_duplicate_invoice = db.stock_movements.count_documents({
            "product_id": product_id,
        })
        with pytest.raises(RuntimeError, match="Sale processing failed"):
            create_sale(db, {
                "payment_method": "cash",
                "idempotency_key": f"duplicate-invoice-{token}",
                "items": [{
                    "product_id": str(product_id),
                    "quantity": 1,
                    "unit_price": "10.00",
                }],
            }, actor=actor)
        assert db.products.find_one({"_id": product_id})["stock_qty"] == stock_before_duplicate_invoice
        assert db.stock_movements.count_documents({
            "product_id": product_id,
        }) == movements_before_duplicate_invoice
