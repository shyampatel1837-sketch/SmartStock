from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, call

import pytest
from bson import Decimal128, ObjectId
from flask import Flask

from app.services.auth_service import register_user
from app.services.product_service import create_product
from app.services.sale_service import create_sale
from app.services.inventory_service import adjust_stock
from app.services.sale_service import void_sale
from app.services.purchase_service import receive_purchase_order


def test_register_user_hashes_password_and_does_not_return_hash():
    database = MagicMock()
    database.users.find_one.return_value = None
    user_id = ObjectId()
    inserted_documents = []
    database.users.insert_one.side_effect = lambda document: (
        inserted_documents.append(dict(document)),
        SimpleNamespace(inserted_id=user_id),
    )[1]
    app = Flask(__name__)
    app.config["BCRYPT_LOG_ROUNDS"] = 4

    with app.app_context():
        user = register_user(database, {
            "username": "store_user",
            "password": "secure-password",
            "role": "sales",
        })

    stored = inserted_documents[0]
    assert stored["password_hash"] != "secure-password"
    assert user["_id"] == str(user_id)
    assert "password_hash" not in user


def test_register_user_rejects_invalid_username_and_short_password():
    database = MagicMock()
    with pytest.raises(ValueError, match="Username"):
        register_user(database, {"username": "x", "password": "long-password"})
    with pytest.raises(ValueError, match="Password"):
        register_user(database, {"username": "valid_user", "password": "short"})
    database.users.find_one.assert_not_called()


def test_sale_stock_is_compensated_if_ledger_insert_fails(application):
    database = MagicMock()
    product_id = ObjectId()
    sale_id = ObjectId()
    database.products.find_one.return_value = {
        "_id": product_id,
        "name": "Test phone",
        "sku": "PHONE-1",
        "selling_price": Decimal128("100.00"),
        "stock_qty": 3,
    }
    database.products.update_one.return_value = SimpleNamespace(modified_count=1)
    database.sales.insert_one.return_value = SimpleNamespace(inserted_id=sale_id)
    database.stock_movements.insert_many.side_effect = RuntimeError("ledger offline")
    counter = MagicMock()
    counter.find_one_and_update.return_value = {"seq": 1}
    database.__getitem__.return_value = counter

    with application.app_context(), pytest.raises(RuntimeError, match="Sale processing failed"):
        create_sale(database, {
            "payment_method": "cash",
            "items": [{
                "product_id": str(product_id),
                "quantity": 1,
                "unit_price": "100.00",
            }],
        })

    assert database.products.update_one.call_args_list == [
        call(
            {"_id": product_id, "status": "active", "stock_qty": {"$gte": 1}},
            {"$inc": {"stock_qty": -1}, "$set": {"updated_at": ANY}},
        ),
        call({"_id": product_id}, {"$inc": {"stock_qty": 1}}),
    ]
    database.stock_movements.delete_many.assert_called_once_with({
        "reference_id": sale_id,
        "reference_type": "sale",
    })
    database.sales.delete_one.assert_called_once_with({"_id": sale_id})
    saved_sale = database.sales.insert_one.call_args.args[0]
    assert saved_sale["items"][0]["unit_price"].to_decimal().to_eng_string() == "100.00"


def test_sale_partial_rollback_does_not_restore_an_item_twice(application):
    database = MagicMock()
    product_ids = [ObjectId() for _ in range(3)]
    products = {
        product_id: {
            "_id": product_id,
            "name": f"Product {index}",
            "sku": f"SKU-{index}",
            "selling_price": Decimal128("10.00"),
            "stock_qty": 2 if index < 3 else 0,
        }
        for index, product_id in enumerate(product_ids, start=1)
    }

    def find_product(query, projection=None):
        return products.get(query["_id"])

    rollback_attempts = []

    def update_product(query, update):
        product_id = query["_id"]
        quantity_change = update["$inc"]["stock_qty"]
        product = products[product_id]
        if quantity_change < 0:
            quantity = -quantity_change
            if product["stock_qty"] < quantity:
                return SimpleNamespace(modified_count=0)
        else:
            rollback_attempts.append(product_id)
            if product_id == product_ids[1]:
                return SimpleNamespace(modified_count=0)
        product["stock_qty"] += quantity_change
        return SimpleNamespace(modified_count=1)

    database.products.find_one.side_effect = find_product
    database.products.update_one.side_effect = update_product
    counter = MagicMock()
    counter.find_one_and_update.return_value = {"seq": 1}
    database.__getitem__.return_value = counter

    with application.app_context(), pytest.raises(
        RuntimeError, match="rollback was incomplete"
    ):
        create_sale(database, {
            "payment_method": "cash",
            "items": [
                {
                    "product_id": str(product_id),
                    "quantity": 1,
                    "unit_price": "10.00",
                }
                for product_id in product_ids
            ],
        })

    assert [products[product_id]["stock_qty"] for product_id in product_ids] == [2, 1, 0]
    assert rollback_attempts == product_ids[:2]
    database.sales.insert_one.assert_not_called()
    database.stock_movements.insert_many.assert_not_called()
    database.stock_movements.delete_many.assert_not_called()


def test_product_creation_records_opening_stock():
    database = MagicMock()
    product_id = ObjectId()
    database.products.find_one.return_value = None
    database.products.insert_one.return_value = SimpleNamespace(inserted_id=product_id)

    product = create_product(database, {
        "sku": "START-001",
        "name": "Opening stock product",
        "category": "Accessories",
        "purchase_cost": "5.00",
        "selling_price": "10.00",
        "stock_qty": "4",
    })

    assert product["stock_qty"] == 4
    movement = database.stock_movements.insert_one.call_args.args[0]
    assert movement["movement_type"] == "opening_stock"
    assert movement["quantity_change"] == 4


def test_stock_adjustment_does_not_overdraw_after_concurrent_change():
    database = MagicMock()
    product_id = ObjectId()
    database.products.find_one.return_value = {"stock_qty": 5, "name": "Product"}
    database.products.update_one.return_value = SimpleNamespace(modified_count=0)

    result = adjust_stock(database, str(product_id), -3, "Damage")

    assert result["success"] is False
    assert "changed during" in result["error"]
    database.stock_movements.insert_one.assert_not_called()


def test_stock_adjustment_rolls_back_when_movement_cannot_be_written():
    database = MagicMock()
    product_id = ObjectId()
    database.products.find_one.return_value = {"stock_qty": 2, "name": "Product"}
    database.products.update_one.side_effect = [
        SimpleNamespace(modified_count=1),
        SimpleNamespace(modified_count=1),
    ]
    database.stock_movements.insert_one.side_effect = RuntimeError("ledger offline")

    with pytest.raises(RuntimeError, match="rolled back"):
        adjust_stock(database, str(product_id), 1, "Count correction")

    assert database.products.update_one.call_count == 2
    database.products.update_one.assert_called_with(
        {"_id": product_id}, {"$inc": {"stock_qty": -1}}
    )


def test_concurrent_sale_void_does_not_restore_stock_twice():
    database = MagicMock()
    sale_id = ObjectId()
    database.sales.find_one.return_value = {
        "_id": sale_id, "status": "completed", "invoice_number": "INV-1"
    }
    database.sales.update_one.return_value = SimpleNamespace(modified_count=0)

    result = void_sale(database, str(sale_id), "Customer cancellation")

    assert result["success"] is False
    database.products.update_one.assert_not_called()


def test_received_purchase_order_cannot_be_received_again():
    database = MagicMock()
    database.purchase_orders.find_one.return_value = {
        "status": "received", "reference": "PO-1", "items": []
    }

    result = receive_purchase_order(database, str(ObjectId()))

    assert result["success"] is False
    database.purchase_orders.update_one.assert_not_called()
    database.products.update_one.assert_not_called()


def test_purchase_receipt_rolls_back_stock_if_movement_insert_fails():
    database = MagicMock()
    order_id = ObjectId()
    product_id = ObjectId()
    database.purchase_orders.find_one.return_value = {
        "_id": order_id,
        "status": "draft",
        "reference": "PO-1",
        "items": [{
            "product_id": product_id,
            "quantity": 3,
            "unit_price": Decimal128("12.00"),
        }],
    }
    database.purchase_orders.update_one.return_value = SimpleNamespace(modified_count=1)
    database.products.find_one.return_value = {"purchase_cost": Decimal128("10.00")}
    database.products.update_one.side_effect = [
        SimpleNamespace(modified_count=1),
        SimpleNamespace(modified_count=1),
    ]
    database.stock_movements.insert_many.side_effect = RuntimeError("ledger offline")

    result = receive_purchase_order(database, str(order_id))

    assert result["success"] is False
    assert database.products.update_one.call_count == 2
    database.products.update_one.assert_called_with(
        {"_id": product_id},
        {"$inc": {"stock_qty": -3}, "$set": {"purchase_cost": Decimal128("10.00")}},
    )
    assert database.purchase_orders.update_one.call_count == 2
