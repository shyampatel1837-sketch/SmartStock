# SmartStock

SmartStock is a Flask and MongoDB inventory application for electronics retailers. It includes a product catalogue, suppliers and purchase orders, point-of-sale sales, stock movement history, review moderation, analytics, and role-based staff accounts.

## Requirements

- Python 3.9 or newer
- MongoDB 5.0 or newer (local MongoDB or MongoDB Atlas)
- A terminal and a browser

## Local setup

From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
```

Edit `.env` and set `MONGO_URI`, `MONGO_DB_NAME`, and a unique `SECRET_KEY`. Generate a secret with:

```sh
python -c "import secrets; print(secrets.token_hex(32))"
```

Start MongoDB, then run:

```sh
python -m scripts.init_db
python run.py
```

Open the address printed by Flask (default `http://127.0.0.1:5000`). The first owner account is created through **Create the owner account** on the sign-in page. Once an owner exists, public registration is closed; owners can create staff accounts through Settings.

`python run.py` is development-only; it uses `APP_ENV` when set, then `FLASK_ENV`, and defaults to development. Production requires a secret key of at least 32 characters and uses secure session cookies. Deploy the WSGI application as `run:app` behind HTTPS with your production WSGI server; the project intentionally does not bundle a server.

## Configuration

See [.env.example](./.env.example). The application does not seed demonstration records. Indexes are created idempotently at startup; `python scripts/init_db.py` checks connectivity and lists the managed indexes. MongoDB connection failures leave the process available for health checks but database-backed requests return HTTP 503 with a configuration hint.

Never commit `.env` or database credentials. `.gitignore` excludes local environment files and virtual environments.

## Tests

Run the automated suite from this directory:

```sh
python -m pytest -q
```

Unit and Flask-template tests do not require a live MongoDB server. Service-level integration checks require a configured MongoDB instance and should be run against a dedicated test database.

The opt-in MongoDB integration test is restricted in code to `localhost`,
`127.0.0.1`, or `::1` and the `smartstock_test` database. It creates uniquely
named test records and removes only records identified by IDs it created; it
does not drop a database or collection. Run it explicitly with:

```sh
SMARTSTOCK_RUN_MONGO_INTEGRATION=1 \
MONGO_URI=mongodb://127.0.0.1:27017/ \
MONGO_DB_NAME=smartstock_test \
.venv/bin/python -m pytest -q tests/test_mongo_integration.py
```

The test exercises service-layer database workflows rather than authenticated
browser routes. It deliberately builds its purchase-order fixture directly to
avoid modifying the application's shared purchase-reference counter.

## Current operational limitations

- Customer returns are not implemented as a separate partial-return/refund workflow. The current supported operation is voiding a completed sale, which restores all sold quantities.
- Multi-document stock changes use conditional updates and compensating writes for application errors. For stronger crash-safe atomicity, deploy MongoDB as a replica set and implement/enable transaction-backed workflows before relying on recovery from process termination mid-operation.
- Inventory valuation uses each product's current purchase cost, not historical weighted-average cost.

See [docs/backup-restore.md](./docs/backup-restore.md) before performing backups or restores.
