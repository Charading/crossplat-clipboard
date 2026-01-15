"""
Clipboard Sync - System Tray Application

Sits in your taskbar and automatically syncs clipboard between PC and iPhone.
Right-click the tray icon for options.

Requirements:
  pip install pystray pillow

Usage:
  python clipboard_tray.py
  (or double-click to run)
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Installing required packages...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pystray", "pillow"], check=True)
    import pystray
    from PIL import Image, ImageDraw

SERVER = os.environ.get("CLIPBOARD_SERVER", "http://localhost:5000")
POLL_INTERVAL = 0.5
HOST = os.environ.get("CLIPBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("CLIPBOARD_PORT", "5000"))


def start_server_thread():
    """Start the embedded server in a background thread."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import json
    from pathlib import Path
    from urllib.parse import urlparse
    
    # Use temp directory for clipboard store
    STORE_PATH = Path(tempfile.gettempdir()) / "clipboard_store.json"
    
    def load_store():
        if STORE_PATH.exists():
            try:
                with STORE_PATH.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def save_store(data):
        try:
            with STORE_PATH.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True, indent=2)
        except Exception:
            pass
    
    class ClipboardHandler(BaseHTTPRequestHandler):
        server_version = "ClipboardServer/0.1"
        
        def log_message(self, format, *args):
            pass  # Suppress server logs
        
        def _send_json(self, status, body):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        
        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
        
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in ("/clip", "/clip/latest"):
                store = load_store()
                if store:
                    self._send_json(200, store)
                else:
                    self._send_json(404, {"error": "No clip available"})
                return
            self._send_json(404, {"error": "Not found"})
        
        def do_POST(self):
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
            
            if clip_type not in ("text", "image"):
                self._send_json(400, {"error": "type must be 'text' or 'image'"})
                return
            if data is None:
                self._send_json(400, {"error": "data is required"})
                return
            
            payload = {
                "type": clip_type,
                "data": data,
                "mime": incoming.get("mime", "text/plain" if clip_type == "text" else "image/png"),
                "source": incoming.get("source", "unknown"),
                "timestamp": time.time(),
            }
            save_store(payload)
            self._send_json(200, {"status": "ok"})
    
    def run_server():
        try:
            server = HTTPServer((HOST, PORT), ClipboardHandler)
            server.serve_forever()
        except Exception as e:
            print(f"Server error: {e}")
    
    server_thread = threading.Thread(target=run_server, daemon=True, name="ServerThread")
    server_thread.start()


class ClipboardSync:
    def __init__(self):
        self.running = True
        self.paused = False
        self.last_local_hash = ""
        self.last_server_hash = ""
        self.last_source = ""
        self.status = "Starting..."
        self.icon = None
        
        # Start the embedded server
        start_server_thread()
        
    def run_ps(self, command: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result

    def get_clipboard_hash(self) -> tuple:
        """Returns (clip_type, data, hash) of current Windows clipboard."""
        script = """
        $img = Get-Clipboard -Format Image -ErrorAction SilentlyContinue
        if ($img) { 'image'; return }
        $txt = Get-Clipboard -Raw -ErrorAction SilentlyContinue
        if ($txt -ne $null) { 'text'; return }
        ''
        """
        result = self.run_ps(script, check=False)
        clip_type = result.stdout.strip()
        
        if clip_type == "text":
            result = self.run_ps("Get-Clipboard -Raw", check=False)
            data = result.stdout
            h = hashlib.md5(data.encode()).hexdigest()
            return ("text", data, h)
        elif clip_type == "image":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp_path = Path(tmp.name)
            path_str = str(tmp_path).replace("'", "''")
            script = (
                "$img = Get-Clipboard -Format Image -ErrorAction Stop;"
                f"$img.Save('{path_str}', [System.Drawing.Imaging.ImageFormat]::Png)"
            )
            try:
                self.run_ps(script)
                data = base64.b64encode(tmp_path.read_bytes()).decode("ascii")
                h = hashlib.md5(data.encode()).hexdigest()
                return ("image", data, h)
            except:
                return ("", "", "")
            finally:
                tmp_path.unlink(missing_ok=True)
        return ("", "", "")

    def fetch_server_clip(self) -> Optional[dict]:
        try:
            with urllib.request.urlopen(f"{SERVER}/clip/latest", timeout=2) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except:
            pass
        return None

    def push_to_server(self, clip_type: str, data: str) -> bool:
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

    def set_text_clipboard(self, text: str) -> None:
        script = f"Set-Clipboard -Value @'\n{text}\n'@"
        self.run_ps(script)

    def set_image_clipboard(self, b64_data: str) -> None:
        # Write image bytes to a temp file
        data = base64.b64decode(b64_data)
        tmp_path = Path(tempfile.gettempdir()) / "clipboard_sync_image.png"
        tmp_path.write_bytes(data)
        path_str = str(tmp_path).replace("\\", "\\\\").replace("'", "''")
        script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$stream = [System.IO.File]::OpenRead('{path_str}')
$img = [System.Drawing.Image]::FromStream($stream)
[System.Windows.Forms.Clipboard]::SetImage($img)
$img.Dispose()
$stream.Close()
$stream.Dispose()
"""
        try:
            self.run_ps(script)
        finally:
            tmp_path.unlink(missing_ok=True)

    def sync_loop(self):
        """Main sync loop running in background thread."""
        while self.running:
            if self.paused:
                time.sleep(0.5)
                continue
                
            try:
                # Check local clipboard
                clip_type, data, local_hash = self.get_clipboard_hash()
                
                # If local clipboard changed AND we didn't just set it from server
                if local_hash and local_hash != self.last_local_hash and self.last_source != "server":
                    self.status = f"Pushing {clip_type}..."
                    if self.push_to_server(clip_type, data):
                        self.status = f"Sent {clip_type} ✓"
                        self.last_server_hash = hashlib.md5(data.encode()).hexdigest()
                    self.last_local_hash = local_hash
                    self.last_source = "local"
                
                # Check server for new clips
                server_clip = self.fetch_server_clip()
                if server_clip:
                    server_data = server_clip.get("data", "")
                    server_hash = hashlib.md5(server_data.encode()).hexdigest()
                    server_source = server_clip.get("source", "")
                    
                    # If server has new data from phone, pull it
                    if server_hash != self.last_server_hash and server_source == "phone":
                        clip_type = server_clip.get("type")
                        self.status = f"Pulling {clip_type}..."
                        
                        if clip_type == "text":
                            self.set_text_clipboard(server_data)
                        elif clip_type == "image":
                            self.set_image_clipboard(server_data)
                        
                        self.status = f"Received {clip_type} ✓"
                        self.last_server_hash = server_hash
                        self.last_local_hash = server_hash
                        self.last_source = "server"
                
                if "..." not in self.status:
                    self.status = "Watching clipboard..."
                    
                time.sleep(POLL_INTERVAL)
                
            except Exception as e:
                self.status = f"Error: {str(e)[:30]}"
                time.sleep(1)

    def create_icon_image(self, color="green"):
        """Create a simple clipboard icon."""
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Clipboard shape
        colors = {
            "green": (76, 175, 80),
            "yellow": (255, 193, 7),
            "red": (244, 67, 54),
            "gray": (158, 158, 158),
        }
        fill = colors.get(color, colors["green"])
        
        # Board
        draw.rounded_rectangle([8, 12, 56, 60], radius=4, fill=fill)
        # Clip at top
        draw.rounded_rectangle([20, 4, 44, 20], radius=3, fill=fill)
        draw.rectangle([24, 12, 40, 18], fill=(255, 255, 255))
        # Lines on clipboard
        draw.rectangle([16, 28, 48, 32], fill=(255, 255, 255, 180))
        draw.rectangle([16, 38, 40, 42], fill=(255, 255, 255, 180))
        draw.rectangle([16, 48, 44, 52], fill=(255, 255, 255, 180))
        
        return img

    def toggle_pause(self, icon, item):
        self.paused = not self.paused
        self.status = "Paused" if self.paused else "Watching clipboard..."

    def quit_app(self, icon, item):
        self.running = False
        icon.stop()

    def get_menu(self):
        return pystray.Menu(
            pystray.MenuItem(lambda text: self.status, lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda text: "Resume" if self.paused else "Pause",
                self.toggle_pause
            ),
            pystray.MenuItem("Quit", self.quit_app),
        )

    def run(self):
        # Start sync thread
        sync_thread = threading.Thread(target=self.sync_loop, daemon=True)
        sync_thread.start()
        
        # Create and run tray icon
        self.icon = pystray.Icon(
            "ClipboardSync",
            self.create_icon_image("green"),
            "Clipboard Sync",
            self.get_menu()
        )
        
        self.icon.run()


def main():
    app = ClipboardSync()
    app.run()


if __name__ == "__main__":
    main()
