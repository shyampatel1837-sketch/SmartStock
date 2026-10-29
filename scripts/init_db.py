"""Verify MongoDB connectivity and the indexes managed by SmartStock."""
from app import create_app
from app.db import get_db, ping
from app.indexes import list_indexes


def main() -> int:
    app = create_app("development")
    with app.app_context():
        if not ping():
            app.logger.error("MongoDB is unavailable; no database setup was completed.")
            return 1
        indexes = list_indexes(get_db())
    for collection, entries in indexes.items():
        names = [entry.get("name", "unknown") for entry in entries if "name" in entry]
        print(f"{collection}: {', '.join(names) if names else 'no indexes listed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
