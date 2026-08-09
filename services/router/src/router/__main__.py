"""Entry point: `uv run python -m router` starts the loopback-only API."""

import uvicorn

from router.config import HOST, PORT


def main() -> None:
    uvicorn.run("router.server:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
