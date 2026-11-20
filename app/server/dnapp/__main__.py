"""python -m dnapp (and the datanuggets-app script): the app on HOST:PORT with one uvicorn
worker; jobs run in the app's own process pool."""

from __future__ import annotations

import logging


def main() -> None:
    import uvicorn

    from dnapp.core.config import Settings
    from dnapp.main import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, workers=1)


if __name__ == "__main__":
    main()
