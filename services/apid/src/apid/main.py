"""Console entrypoint for the apid combined API service."""

from __future__ import annotations

import uvicorn

from apid.app import create_app
from apid.settings import ApidSettings


def main() -> None:
    settings = ApidSettings()
    host, _, port = settings.listen_addr.rpartition(":")
    host = host or "0.0.0.0"
    port_str = port or "8080"
    app = create_app()
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
