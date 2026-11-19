"""Start the local DevPilot API server."""

import ipaddress
import os

import uvicorn


def main() -> None:
    host = os.getenv("DEVPILOT_HOST", "127.0.0.1")
    if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
        raise ValueError("DevPilot only supports loopback addresses; do not expose the approval API publicly.")
    uvicorn.run(
        "devpilot.api:app",
        host=host,
        port=int(os.getenv("DEVPILOT_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
