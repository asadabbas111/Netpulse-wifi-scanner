"""NetPulse — professional LAN / Wi‑Fi network utility for Windows."""

from __future__ import annotations

import sys

from app.gui.main_window import run_app


def main() -> int:
    if sys.platform != "win32":
        print("NetPulse currently supports Windows only.")
        return 1
    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
