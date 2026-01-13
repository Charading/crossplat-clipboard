"""
Clipboard Sync - Background service that automatically syncs clipboard between PC and server.

- Watches Windows clipboard for changes → auto-push to server
- Polls server for new clips → auto-set Windows clipboard

Usage:
  python clipboard_sync.py

Press Ctrl+C to stop.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVER = os.environ.get("CLIPBOARD_SERVER", "http://localhost:5000")
POLL_INTERVAL = 0.5  # seconds between server checks


def run_ps(command: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def get_clipboard_hash() -> tuple[str, str, str]:
    """Returns (clip_type, data, hash) of current Windows clipboard."""
    # Check for image first
    script = """
    $img = Get-Clipboard -Format Image -ErrorAction SilentlyContinue
    if ($img) { 'image'; return }
    $txt = Get-Clipboard -Raw -ErrorAction SilentlyContinue
    if ($txt -ne $null) { 'text'; return }
    ''
    """
    result = run_ps(script, check=False)
    clip_type = result.stdout.strip()
    
    if clip_type == "text":
        result = run_ps("Get-Clipboard -Raw", check=False)
        data = result.stdout
        h = hashlib.md5(data.encode()).hexdigest()
        return ("text", data, h)
    elif clip_type == "image":
        # Get image bytes for hashing
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp_path = Path(tmp.name)
        path_str = str(tmp_path).replace("'", "''")
        script = (
            "$img = Get-Clipboard -Format Image -ErrorAction Stop;"
            f"$img.Save('{path_str}', [System.Drawing.Imaging.ImageFormat]::Png)"
        )
        try:
            run_ps(script)
            data = base64.b64encode(tmp_path.read_bytes()).decode("ascii")
            h = hashlib.md5(data.encode()).hexdigest()
            return ("image", data, h)
        except:
            return ("", "", "")
        finally:
            tmp_path.unlink(missing_ok=True)
    return ("", "", "")


def fetch_server_clip() -> dict | None:
    """Fetch current clip from server."""
    try:
        with urllib.request.urlopen(f"{SERVER}/clip/latest", timeout=2) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except:
        pass
    return None


def push_to_server(clip_type: str, data: str) -> bool:
    """Push clip to server."""
    payload = {
        "type": clip_type,
        "data": data,
        "mime": "text/plain" if clip_type == "text" else "image/png",
        "source": "desktop"
    }
    try:
        req = urllib.request.Request(
            f"{SERVER}/clip",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except:
        return False


def set_text_clipboard(text: str) -> None:
    """Set Windows clipboard to text."""
    script = f"Set-Clipboard -Value @'\n{text}\n'@"
    run_ps(script)


def set_image_clipboard(b64_data: str) -> None:
    """Set Windows clipboard to image."""
    data = base64.b64decode(b64_data)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(data)
    path_str = str(tmp_path).replace("'", "''")
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


def main():
    print(f"🔄 Clipboard Sync started - watching {SERVER}")
    print("   Press Ctrl+C to stop\n")
    
    last_local_hash = ""
    last_server_hash = ""
    last_source = ""
    
    while True:
        try:
            # Check local clipboard
            clip_type, data, local_hash = get_clipboard_hash()
            
            # If local clipboard changed AND we didn't just set it from server
            if local_hash and local_hash != last_local_hash and last_source != "server":
                print(f"📤 Pushing {clip_type} to server...")
                if push_to_server(clip_type, data):
                    print(f"   ✓ Sent {clip_type}")
                    last_server_hash = hashlib.md5(data.encode()).hexdigest()
                last_local_hash = local_hash
                last_source = "local"
            
            # Check server for new clips
            server_clip = fetch_server_clip()
            if server_clip:
                server_data = server_clip.get("data", "")
                server_hash = hashlib.md5(server_data.encode()).hexdigest()
                server_source = server_clip.get("source", "")
                
                # If server has new data from phone, pull it
                if server_hash != last_server_hash and server_source == "phone":
                    clip_type = server_clip.get("type")
                    print(f"📥 Pulling {clip_type} from server...")
                    
                    if clip_type == "text":
                        set_text_clipboard(server_data)
                    elif clip_type == "image":
                        set_image_clipboard(server_data)
                    
                    print(f"   ✓ Clipboard updated")
                    last_server_hash = server_hash
                    last_local_hash = server_hash  # Prevent re-pushing what we just pulled
                    last_source = "server"
            
            time.sleep(POLL_INTERVAL)
            
        except KeyboardInterrupt:
            print("\n👋 Clipboard Sync stopped")
            break
        except Exception as e:
            print(f"⚠️  Error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
