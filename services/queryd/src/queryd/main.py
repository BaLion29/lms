"""Console entrypoint for the queryd service."""

from __future__ import annotations

import uvicorn

from queryd.app import create_app
from queryd.settings import Settings


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    host, _, port = settings.listen_addr.rpartition(":")
    host = host or "0.0.0.0"
    port_str = port or "8087"
    app = create_app(settings)
    uvicorn.run(
        app,
        host=host,
        port=int(port_str),
        log_level=settings.log_level.lower(),
        proxy_headers=settings.proxy_headers,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
