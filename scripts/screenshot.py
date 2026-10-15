#!/usr/bin/env python3
"""Drive the game in a headless browser and save screenshots. Dev tool, not part of the app.

    python3 scripts/screenshot.py OUTDIR [--dark]

Starts the app on a free local port, plays the steps listed in PLAN, and screenshots each page.
"""
import socket
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exposure_sim import create_app  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(outdir: str, dark: bool, plan: list[tuple[str, str, dict | None]], width: int = 1440):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server = make_server("127.0.0.1", port, create_app({"SECRET_KEY": "shots"}))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1000},
                                color_scheme="dark" if dark else "light")
        for name, path, form in plan:
            if path:                      # empty path = act on the page already open
                page.goto(base + path)
            if form:
                for field, values in form.items():
                    if field == "action":
                        continue
                    for v in values if isinstance(values, list) else [values]:
                        loc = page.locator(f'[name="{field}"][value="{v}"]')
                        if loc.count():
                            loc.first.check()
                        else:
                            page.select_option(f'select[name="{field}"]', v)
                page.click(f'button[name="action"][value="{form.get("action", "check")}"]')
                page.wait_for_load_state()
            page.screenshot(path=str(out / f"{name}.png"), full_page=True)
        browser.close()
    server.shutdown()


if __name__ == "__main__":
    import json
    plan = json.loads(Path(sys.argv[2]).read_text())
    main(sys.argv[1], "--dark" in sys.argv, plan, width=int(next((a.split("=")[1] for a in sys.argv if a.startswith("--width=")), 1440)))
