"""Entry point: python3 -m driftwall.ui [--config PATH]"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stdout,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
# Silence noisy third-party HTTP debug logs
for _noisy in ("httpcore", "httpx", "urllib3", "chromadb"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(prog="driftwall ui")
    parser.add_argument("--config", metavar="PATH", default=None)
    args = parser.parse_args()

    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import Gtk
    except (ImportError, ValueError) as e:
        print(f"GTK3 / AyatanaAppIndicator3 not available: {e}", file=sys.stderr)
        sys.exit(1)

    from driftwall.ui.app import DriftwallApp

    app = DriftwallApp(config_path=args.config)
    app.setup()
    Gtk.main()


main()
