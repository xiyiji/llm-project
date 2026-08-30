"""Entry point: start the exception handler API."""

import uvicorn

from app.api import app  # noqa: F401
from app.config import get_config

if __name__ == "__main__":
    config = get_config()
    uvicorn.run(app, host=config.api.host, port=config.api.port)
