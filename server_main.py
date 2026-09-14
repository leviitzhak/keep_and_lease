"""Development and container entry point for the computation API."""

import os

import uvicorn

from server.app import app
from server.replay_extensions import install as install_replay_extensions
from server.strategy_catalog import install as install_strategy_catalog


if __name__ == "__main__":
    install_strategy_catalog(app)
    install_replay_extensions(app)
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
