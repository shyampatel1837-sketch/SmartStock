"""
SmartStock – Analytics Service

All dashboard numbers come from MongoDB aggregation pipelines.
No fake data, no in-Python filtering of entire collections.

Costing method: current purchase_cost per product × stock_qty.
Limitation: this reflects current cost, not weighted-average historical cost.
This is documented here and in the report.
"""
from __future__ import annotations
import datetime
from bson import ObjectId, Decimal128
from pymongo.database import Database
from ..utils import mongo_doc_to_dict, utcnow


def get_dashboard_summary(db: Database) -> dict:
    """Return all KPIs for the main dashboard."""
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    return {
        "products": _product_summary(db),
        "sales_this_month": _sales_summary(db, month_start, now),
        "low_stock_count": _low_stock_count(db),
        "recent_movements": _recent_movements(db, limit=10),
        "top_products": _top_selling_products(db, limit=5),
        "revenue_by_category": _revenue_by_category(db, month_start, now),
        "inventory_value": _inventory_value(db),
        "avg_ratings": _top_rated_products(db, min_reviews=3, limit=5),
    }


def _product_summary(db: Database) -> dict:
    pipeline = [
        {"$match": {"status": {"$ne": "discontinued"}}},
        {
            "$group": {
                "_id": None,
                "total_products": {"$sum": 1},
                "total_stock_units": {"$sum": "$stock_qty"},
                "out_of_stock": {
                    "$sum": {"$cond": [{"$eq": ["$stock_qty", 0]}, 1, 0]}
                },
            }
        },
    ]
    result = list(db.products.aggregate(pipeline))
    if not result:
        return {"total_products": 0, "total_stock_units": 0, "out_of_stock": 0}
    r = result[0]
    return {
        "total_products": r["total_products"],
        "total_stock_units": r["total_stock_units"],
        "out_of_stock": r["out_of_stock"],
    }


def _sales_summary(db: Database, date_from: datetime.datetime,
                   date_to: datetime.datetime) -> dict:
    pipeline = [
        {
            "$match": {
                "status": "completed",
                "sale_date": {"$gte": date_from, "$lte": date_to},
            }
        },
        {
            "$group": {
                "_id": None,
                "revenue": {"$sum": {"$toDouble": "$total_amount"}},
                "count": {"$sum": 1},
            }
        },
    ]
    result = list(db.sales.aggregate(pipeline))
    if not result:
        return {"revenue": 0.0, "count": 0}
    r = result[0]
    return {"revenue": round(r["revenue"], 2), "count": r["count"]}


def _low_stock_count(db: Database) -> int:
    return db.products.count_documents(
        {
            "status": {"$ne": "discontinued"},
            "$expr": {
                "$and": [
                    {"$gt": ["$stock_qty", 0]},
                    {"$lte": ["$stock_qty", "$reorder_threshold"]},
                ]
            },
        }
    )


def _recent_movements(db: Database, limit: int = 10) -> list:
    pipeline = [
        {"$sort": {"created_at": -1}},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "products",
                "localField": "product_id",
                "foreignField": "_id",
                "as": "product",
            }
        },
        {"$unwind": {"path": "$product", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "movement_type": 1,
                "quantity_change": 1,
                "reason": 1,
                "created_at": 1,
                "product_name": "$product.name",
                "product_sku": "$product.sku",
            }
        },
    ]
    return [mongo_doc_to_dict(d) for d in db.stock_movements.aggregate(pipeline)]


def _top_selling_products(db: Database, limit: int = 10,
                          date_from=None, date_to=None) -> list:
    match: dict = {"status": "completed"}
    if date_from:
        match["sale_date"] = {"$gte": date_from}
    if date_to:
        match.setdefault("sale_date", {})["$lte"] = date_to
    pipeline = [
        {"$match": match},
        {"$unwind": "$items"},
        {
            "$group": {
                "_id": "$items.product_id",
                "product_name": {"$first": "$items.product_name"},
                "product_sku": {"$first": "$items.product_sku"},
                "units_sold": {"$sum": "$items.quantity"},
                "revenue": {"$sum": {"$toDouble": "$items.line_total"}},
            }
        },
        {"$sort": {"units_sold": -1}},
        {"$limit": limit},
    ]
    return [mongo_doc_to_dict(d) for d in db.sales.aggregate(pipeline)]


def _revenue_by_category(db: Database, date_from=None, date_to=None) -> list:
    """Revenue by product category using $lookup."""
    match: dict = {"status": "completed"}
    if date_from:
        match["sale_date"] = {"$gte": date_from}
    if date_to:
        match.setdefault("sale_date", {})["$lte"] = date_to
    pipeline = [
        {"$match": match},
        {"$unwind": "$items"},
        {
            "$lookup": {
                "from": "products",
                "localField": "items.product_id",
                "foreignField": "_id",
                "as": "product",
            }
        },
        {"$unwind": {"path": "$product", "preserveNullAndEmptyArrays": True}},
        {
            "$group": {
                "_id": "$product.category",
                "revenue": {"$sum": {"$toDouble": "$items.line_total"}},
                "units_sold": {"$sum": "$items.quantity"},
            }
        },
        {"$sort": {"revenue": -1}},
        {"$project": {"_id": 0, "category": "$_id", "revenue": 1, "units_sold": 1}},
    ]
    return [mongo_doc_to_dict(d) for d in db.sales.aggregate(pipeline)]


def _inventory_value(db: Database) -> dict:
    """
    Inventory value by category.
    Value = sum(purchase_cost × stock_qty) — using current purchase_cost.
    """
    pipeline = [
        {"$match": {"status": {"$ne": "discontinued"}, "stock_qty": {"$gt": 0}}},
        {
            "$group": {
                "_id": "$category",
                "total_value": {
                    "$sum": {
                        "$multiply": [
                            {"$toDouble": "$purchase_cost"},
                            "$stock_qty",
                        ]
                    }
                },
                "total_units": {"$sum": "$stock_qty"},
                "product_count": {"$sum": 1},
            }
        },
        {"$sort": {"total_value": -1}},
        {
            "$project": {
                "_id": 0,
                "category": "$_id",
                "total_value": 1,
                "total_units": 1,
                "product_count": 1,
            }
        },
    ]
    rows = [mongo_doc_to_dict(d) for d in db.products.aggregate(pipeline)]
    grand_total = sum(r.get("total_value", 0) for r in rows)
    return {"by_category": rows, "grand_total": round(grand_total, 2)}


def _top_rated_products(db: Database, min_reviews: int = 3,
                        limit: int = 10) -> list:
    pipeline = [
        {"$match": {"status": "approved"}},
        {
            "$group": {
                "_id": "$product_id",
                "average_rating": {"$avg": "$rating"},
                "review_count": {"$sum": 1},
            }
        },
        {"$match": {"review_count": {"$gte": min_reviews}}},
        {"$sort": {"average_rating": -1, "review_count": -1}},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "products",
                "localField": "_id",
                "foreignField": "_id",
                "as": "product",
            }
        },
        {"$unwind": {"path": "$product", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "_id": 0,
                "product_id": "$_id",
                "product_name": "$product.name",
                "product_sku": "$product.sku",
                "category": "$product.category",
                "average_rating": {"$round": ["$average_rating", 2]},
                "review_count": 1,
            }
        },
    ]
    return [mongo_doc_to_dict(d) for d in db.reviews.aggregate(pipeline)]


def sales_over_time(db: Database, date_from: datetime.datetime,
                    date_to: datetime.datetime, group_by: str = "day") -> list:
    """Daily or monthly revenue aggregation."""
    date_format = "%Y-%m-%d" if group_by == "day" else "%Y-%m"
    pipeline = [
        {
            "$match": {
                "status": "completed",
                "sale_date": {"$gte": date_from, "$lte": date_to},
            }
        },
        {
            "$group": {
                "_id": {"$dateToString": {"format": date_format, "date": "$sale_date"}},
                "revenue": {"$sum": {"$toDouble": "$total_amount"}},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "date": "$_id", "revenue": 1, "count": 1}},
    ]
    return [mongo_doc_to_dict(d) for d in db.sales.aggregate(pipeline)]


def brand_counts(db: Database) -> list:
    pipeline = [
        {"$match": {"status": {"$ne": "discontinued"}}},
        {"$group": {"_id": "$brand", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
        {"$project": {"_id": 0, "brand": "$_id", "count": 1}},
    ]
    return [mongo_doc_to_dict(d) for d in db.products.aggregate(pipeline)]


def stock_movement_summary(db: Database, days: int = 30) -> list:
    since = utcnow() - datetime.timedelta(days=days)
    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {
            "$group": {
                "_id": "$movement_type",
                "total_qty": {"$sum": "$quantity_change"},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1}},
        {"$project": {"_id": 0, "movement_type": "$_id", "total_qty": 1, "count": 1}},
    ]
    return [mongo_doc_to_dict(d) for d in db.stock_movements.aggregate(pipeline)]
