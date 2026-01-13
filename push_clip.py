"""
Push current Windows clipboard (text or image) to the local clipboard server.

Usage:
  python push_clip.py

Server URL can be overridden with CLIPBOARD_SERVER env var (default: http://localhost:5000).
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

SERVER = os.environ.get("CLIPBOARD_SERVER", "http://localhost:5000")


def run_ps(command: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def detect_clip_type() -> str:
    script = """
    $img = Get-Clipboard -Format Image -ErrorAction SilentlyContinue
    if ($img) { 'image'; return }
    $txt = Get-Clipboard -Raw -ErrorAction SilentlyContinue
    if ($txt -ne $null) { 'text'; return }
    ''
    """
    result = run_ps(script)
    return result.stdout.strip()


def get_text() -> str:
    result = run_ps("Get-Clipboard -Raw")
    return result.stdout


def get_image_base64() -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp_path = Path(tmp.name)
    path_str = str(tmp_path).replace("'", "''")
    script = (
        "$img = Get-Clipboard -Format Image -ErrorAction Stop;"
        f"$img.Save('{path_str}', [System.Drawing.Imaging.ImageFormat]::Png)"
    )
    run_ps(script)
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)
    return base64.b64encode(data).decode("ascii")


def post_clip(payload: dict) -> None:
    req = urllib.request.Request(
        f"{SERVER}/clip",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Server responded with {resp.status}")


def main() -> None:
    clip_type = detect_clip_type()
    if not clip_type:
        print("Clipboard is empty or unsupported.")
        sys.exit(1)

    if clip_type == "text":
        text = get_text()
        payload = {"type": "text", "data": text, "mime": "text/plain", "source": "desktop"}
    else:
        try:
            b64 = get_image_base64()
        except Exception as exc:
            print(f"Failed to read image from clipboard: {exc}")
            sys.exit(1)
        payload = {"type": "image", "data": b64, "mime": "image/png", "source": "desktop"}

    try:
        post_clip(payload)
        print(f"Sent {clip_type} to server at {SERVER}")
    except urllib.error.URLError as exc:
        print(f"Failed to reach server: {exc}")
        sys.exit(1)
    except Exception as exc:  # pragma: no cover
        print(f"Failed to push clipboard: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
