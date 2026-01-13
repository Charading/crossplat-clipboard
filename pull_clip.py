"""
Pull the latest clip from the local clipboard server and set it on the Windows clipboard.

Usage:
  python pull_clip.py

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


def fetch_clip() -> dict:
    with urllib.request.urlopen(f"{SERVER}/clip/latest") as resp:
        if resp.status != 200:
            raise RuntimeError(f"Server responded with {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def set_text(text: str) -> None:
    # Use a here-string to avoid quoting issues.
    script = f"Set-Clipboard -Value @'\n{text}\n'@"
    run_ps(script)


def set_image_from_base64(b64_data: str) -> None:
    data = base64.b64decode(b64_data)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(data)
    path_str = str(tmp_path).replace("'", "''")
    # Use .NET to load image and set clipboard directly (avoids file deletion race)
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile('{path_str}')
[System.Windows.Forms.Clipboard]::SetImage($img)
$img.Dispose()
"""
    try:
        run_ps(script)
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    try:
        clip = fetch_clip()
    except urllib.error.URLError as exc:
        print(f"Failed to reach server: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to fetch clip: {exc}")
        sys.exit(1)

    clip_type = clip.get("type")
    data = clip.get("data")
    if clip_type == "text":
        try:
            set_text(data or "")
            print("Copied latest text from server to clipboard.")
        except Exception as exc:
            print(f"Failed to set text clipboard: {exc}")
            sys.exit(1)
    elif clip_type == "image":
        try:
            set_image_from_base64(data or "")
            print("Copied latest image from server to clipboard.")
        except Exception as exc:
            print(f"Failed to set image clipboard: {exc}")
            sys.exit(1)
    else:
        print("Server returned no clip or unsupported type.")
        sys.exit(1)


if __name__ == "__main__":
    main()
