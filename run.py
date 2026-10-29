"""Development entry point for SmartStock."""
import os

from app import create_app


configuration = os.environ.get(
    "APP_ENV", os.environ.get("FLASK_ENV", "development")
)
app = create_app(configuration)


if __name__ == "__main__":
    if not app.config["DEBUG"]:
        raise SystemExit(
            "run.py is for development only; use a production WSGI server for run:app."
        )
    app.run(
        host=app.config["FLASK_HOST"],
        port=app.config["FLASK_PORT"],
        debug=app.config["DEBUG"],
    )
