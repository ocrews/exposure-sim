#!/usr/bin/env python3
"""Render every scenario's map in a real browser and measure the text.

Fails if any label runs past its box or two labels in a box collide. SVG text doesn't wrap,
so this is the only reliable way to know a label fits once real fonts are applied.

    python3 scripts/check_map.py
"""
import socket
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exposure_sim import create_app  # noqa: E402
from exposure_sim.topology import Overlay, TopologyBuilder  # noqa: E402

MEASURE = """
() => {
  const problems = [];
  document.querySelectorAll('.map .node').forEach(g => {
    const r = g.querySelector('rect').getBBox();
    const boxes = [...g.querySelectorAll('text')].map(t => ({t: t.textContent, b: t.getBBox()}));
    boxes.forEach(({t, b}) => {
      if (b.x < r.x + 3 || b.x + b.width > r.x + r.width - 3) problems.push(`${g.dataset.id}: "${t}" overflows`);
    });
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i].b, c = boxes[j].b;
      if (a.x < c.x + c.width && c.x < a.x + a.width && a.y < c.y + c.height && c.y < a.y + a.height)
        problems.push(`${g.dataset.id}: "${boxes[i].t}" overlaps "${boxes[j].t}"`);
    }
  });
  return problems;
}
"""


def main() -> int:
    app = create_app({"SECRET_KEY": "check"})
    # Render each scenario with every overlay turned on, so overlay nodes are measured too
    pages = {}
    with app.test_request_context():
        from flask import render_template
        for s in app.extensions["scenarios"].all():
            for model in ("saas_collector", "onprem"):
                ov = Overlay(connected={x.id for x in s.sources}, reveal_gaps=True, deployment=model,
                             collector_targets=s.onprem_endpoints, crown_jewels=s.crown_jewels)
                layout = TopologyBuilder(s, ov).build()
                pages[f"{s.id}-{model}"] = render_template("map_only.html", layout=layout, scenario=s)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = make_server("127.0.0.1", port, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.goto(f"http://127.0.0.1:{port}/")   # same origin, so the stylesheet and fonts load
        for name, html in pages.items():
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            for problem in page.evaluate(MEASURE):
                failures.append(f"{name}: {problem}")
        browser.close()
    server.shutdown()
    print("\n".join(failures) or f"All labels fit ({len(pages)} maps checked).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
