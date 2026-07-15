"""Console entrypoint for the captured service."""

from __future__ import annotations

import uvicorn

from captured.app import create_app
from captured.settings import Settings


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    host, _, port = settings.listen_addr.rpartition(":")
    host = host or "0.0.0.0"
    port_str = port or "8088"
    app = create_app(settings)
    uvicorn.run(app, host=host, port=int(port_str), log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
