"""Run the web UI: `python -m g1r`."""

import uvicorn

from g1r.config import load_settings
from g1r.web.app import create_app


def main() -> None:
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.server.host, port=settings.server.port)


if __name__ == "__main__":
    main()
