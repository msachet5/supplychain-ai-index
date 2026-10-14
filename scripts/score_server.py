#!/usr/bin/env python3
"""Local scoring mode: serves site/ and saves hand scores back to data/process_scores.csv.

GET  /api/scores  latest score row per process (JSON)
POST /api/scores  {process_id, capability, adoption, rationale, override_note}
                  appends a new version row, then rebuilds site/data.js

Binds to 127.0.0.1 only. Writes only data/process_scores.csv. The published static site
has no /api/scores, so the editor never appears there.

Usage: python3 -I scripts/score_server.py [port]   (default 8766)
"""

import csv
import json
import subprocess
import sys
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "data" / "process_scores.csv"
FIELDS = ["process_id", "version", "capability", "adoption", "ai_type", "digital_share", "data_readiness",
          "decision_stakes", "scored_by", "scored_on", "rationale", "override_note"]
MAX_BODY = 20_000
MAX_TEXT = 400


def read_rows():
    with SCORES.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def latest(rows):
    best = {}
    for r in rows:
        if r["process_id"] not in best or int(r["version"]) > int(best[r["process_id"]]["version"]):
            best[r["process_id"]] = r
    return best


def clean_text(value):
    return " ".join(str(value or "").split())[:MAX_TEXT]


def score(value, name):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not 0 <= v <= 10:
        raise ValueError(f"{name} must be between 0 and 10")
    return f"{v:g}"


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/scores":
            return self.send_json(200, latest(read_rows()))
        if path == "/scoring.js":
            body = b"window.SCAI_SCORING = true;\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/scores":
            return self.send_json(404, {"error": "not found"})
        # Only same-origin JSON requests: a JSON content type forces a CORS preflight,
        # which this server never grants, so other sites cannot post here.
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.send_json(415, {"error": "expected application/json"})
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            return self.send_json(403, {"error": "cross-origin request refused"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            return self.send_json(413, {"error": "body too large or empty"})
        try:
            body = json.loads(self.rfile.read(length))
            rows = read_rows()
            current = latest(rows).get(str(body.get("process_id")))
            if not current:
                raise ValueError("unknown process_id")
            rationale = clean_text(body.get("rationale"))
            if not rationale:
                raise ValueError("a reason is required")
            new = dict(current)
            new.update({
                "version": str(int(current["version"]) + 1),
                "capability": score(body.get("capability"), "capability"),
                "adoption": score(body.get("adoption"), "adoption"),
                "scored_by": "llm+expert" if current["scored_by"] in ("llm", "llm+expert") else "expert",
                "scored_on": date.today().isoformat(),
                "rationale": rationale,
                "override_note": clean_text(body.get("override_note")),
            })
        except (ValueError, json.JSONDecodeError) as err:
            return self.send_json(400, {"error": str(err)})

        with SCORES.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writerow({k: new.get(k, "") for k in FIELDS})
        build = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "build_site_data.py")],
                               capture_output=True, text=True)
        if build.returncode != 0:
            return self.send_json(500, {"error": f"saved, but rebuild failed: {build.stderr[-300:]}"})
        self.log_message("saved %s v%s (capability %s, adoption %s)", new["process_id"], new["version"],
                         new["capability"], new["adoption"])
        return self.send_json(200, {"ok": True, "version": new["version"]})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    handler = partial(Handler, directory=str(ROOT / "site"))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Scoring mode at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
