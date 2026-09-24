"""Dashboard server entrypoint.

Run:
    python -m app.dashboard.server
or:
    uvicorn app.dashboard.api:app
"""
from __future__ import annotations

from app.core import config
from app.dashboard.api import create_app
from app.core.logger import log


def main() -> None:
    import uvicorn
    app = create_app()
    log("DASHBOARD", "Starting dashboard at http://{}:{}".format(
        config.DASHBOARD_HOST, config.DASHBOARD_PORT))
    uvicorn.run(app, host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT, log_level="warning")


if __name__ == "__main__":
    main()