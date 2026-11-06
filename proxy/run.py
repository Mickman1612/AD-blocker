"""Starts the filtering app. Windows runs this at sign-in with no window."""
import asyncio
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from proxy import app  # noqa: E402
from proxy.server import ProxyServer  # noqa: E402

ADDRESS_IN_USE = 10048
RESTART_DELAY_SECONDS = 5


async def serve():
    server = ProxyServer(app.load_config())
    await server.start()
    (app.data_dir() / "running.pid").write_text(str(os.getpid()), encoding="ascii")
    await server.serve_forever()


def main():
    while True:
        try:
            asyncio.run(serve())
        except OSError as error:
            if getattr(error, "winerror", None) == ADDRESS_IN_USE or error.errno == ADDRESS_IN_USE:
                return  # Already running.
            time.sleep(RESTART_DELAY_SECONDS)
        except Exception:  # Browsing falls back to direct while this restarts.
            time.sleep(RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    main()
