# MongoDB backup and restore

Use the MongoDB Database Tools (`mongodump` and `mongorestore`) and the same authenticated URI used by SmartStock. Avoid placing credentials directly in shell history; use a protected environment variable or an approved MongoDB config file.

## Create a compressed archive

```sh
mongodump --uri "$MONGO_URI" --db "$MONGO_DB_NAME" \
  --archive="smartstock-backup.archive" --gzip
```

Keep the archive in an access-controlled backup location, not in the application repository. Verify that the command exits successfully and retain the output and timestamp according to the store's retention policy.

## Verify a restore without replacing the live database

Restore into a new database name first:

```sh
mongorestore --uri "$MONGO_URI" --gzip \
  --archive="smartstock-backup.archive" \
  --nsFrom="${MONGO_DB_NAME}.*" \
  --nsTo="smartstock_restore_check.*"
```

Set `MONGO_DB_NAME=smartstock_restore_check` in a temporary local configuration and run the application against that database. Check login, product and supplier records, purchases, sales, stock movements, reviews, and analytics before treating the archive as verified.

Do not point a restore at the live database or use `mongorestore --drop` during routine verification. Promotion of a verified restore should be planned as a separate maintenance operation with a fresh backup and a controlled configuration change.
