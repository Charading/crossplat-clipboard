"""Simple local clipboard server (no encryption).

Endpoints:
- POST /clip with JSON: { "type": "text"|"image", "data": "...", "mime": "optional", "source": "optional" }
- GET  /clip or /clip/latest returns the latest clip payload.

Stores the latest clip in a JSON file next to this script so the service can restart without losing data.
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

HOST = os.environ.get("CLIPBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("CLIPBOARD_PORT", "5000"))
STORE_PATH = Path(__file__).with_name("clipboard_store.json")


def load_store() -> Dict[str, Any]:
    if STORE_PATH.exists():
        try:
            with STORE_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_store(data: Dict[str, Any]) -> None:
    try:
        with STORE_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)
    except Exception as exc:  # pragma: no cover - best effort
        print(f"Failed to persist clipboard store: {exc}")


class ClipboardHandler(BaseHTTPRequestHandler):
    server_version = "ClipboardServer/0.1"

    def _send_json(self, status: int, body: Dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/clip", "/clip/latest"):
            store = load_store()
            if store:
                self._send_json(200, store)
            else:
                self._send_json(404, {"error": "No clip available"})
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/clip":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._send_json(400, {"error": "Missing body"})
            return

        try:
            raw = self.rfile.read(length)
            incoming = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        clip_type = incoming.get("type")
        data = incoming.get("data")
        mime = incoming.get("mime")
        source = incoming.get("source")

        if clip_type not in ("text", "image"):
            self._send_json(400, {"error": "type must be 'text' or 'image'"})
            return
        if data is None:
            self._send_json(400, {"error": "data is required"})
            return

        payload = {
            "type": clip_type,
            "data": data,
            "mime": mime or ("text/plain" if clip_type == "text" else "image/png"),
            "source": source or "desktop",
            "createdAt": int(time.time()),
        }

        save_store(payload)
        self._send_json(200, {"status": "ok"})


def main() -> None:
    server = HTTPServer((HOST, PORT), ClipboardHandler)
    print(f"Serving clipboard at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
