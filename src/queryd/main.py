"""Console entrypoint for the queryd service."""

from __future__ import annotations

import uvicorn

from queryd.app import create_app
from queryd.settings import Settings


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    host, _, port = settings.listen_addr.rpartition(":")
    app = create_app(settings)
    uvicorn.run(app, host=host, port=int(port))


if __name__ == "__main__":
    main()
