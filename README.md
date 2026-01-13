# iPhone ↔ PC Clipboard Sync

Auto-sync clipboard between your Windows PC and iPhone over local Wi-Fi. Copy on one device, paste on the other — automatically!

## Quick Start

### 1. Start the Server
```powershell
python server.py
```

### 2. Get Your PC's IP
```powershell
ipconfig
```
(Look for IPv4 Address, e.g., `192.168.1.100`)

### 3. Launch the Tray App
```powershell
python clipboard_tray.py
```
Green clipboard icon appears in system tray. Done! Now everything syncs automatically.

---

## iPhone Shortcuts

### 📤 Push Text to PC

1. **Get Clipboard**
2. **Get Contents of URL**
   - URL: `http://<YOUR-PC-IP>:5000/clip`
   - Method: **POST**
   - Body (JSON):
     - `type`: `text`
     - `data`: `[Clipboard]`
     - `mime`: `text/plain`
     - `source`: `phone`

### 📸 Push Photo to PC

1. **Choose from Menu**:
   - Camera → **Take Photo**
   - Photo Library → **Select Photos**
2. **Convert Image** to PNG
3. **Encode** with Base64
4. **Get Contents of URL**
   - URL: `http://<YOUR-PC-IP>:5000/clip`
   - Method: **POST**
   - Body (JSON):
     - `type`: `image`
     - `data`: `[Base64 Encoded]`
     - `mime`: `image/png`
     - `source`: `phone`

### 📥 Pull from PC

1. **Get Contents of URL** → `http://<YOUR-PC-IP>:5000/clip/latest` (GET)
2. **Get Value** for `data`
3. **Copy to Clipboard**

(For images: insert **Decode Base64** before copying)

---

## Windows Startup

To run the tray app automatically on boot:

```powershell
# Build the EXE
pip install pyinstaller
pyinstaller --onefile --noconsole --name ClipboardSync clipboard_tray.py

# Copy to startup
$startup = [Environment]::GetFolderPath('Startup')
Copy-Item "dist\ClipboardSync.exe" -Destination $startup
```

---

## Files

| File | Purpose |
|------|---------|
| `server.py` | HTTP server storing clipboard data |
| `clipboard_tray.py` | Auto-sync background app (recommended) |
| `push_clip.py` | Manual push to server |
| `pull_clip.py` | Manual pull from server |
| `clipboard_sync.py` | Alternative sync script |

---

## How It Works

1. **Server** stores the latest clipboard (text or image)
2. **Tray App** watches your PC clipboard for changes and auto-pushes
3. **Tray App** polls server for iPhone changes and auto-pulls
4. **iPhone Shortcuts** can manually push/pull anytime

---

## Security

⚠️ **No encryption** — keep the server on trusted networks only!

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Image not pasting | Check Base64 encoding in shortcut; verify image size |
| Shortcut won't run | Verify PC IP is correct; ensure server is running; check firewall |
| App crashes | Try running `python clipboard_tray.py` directly to see errors |

---

## Optional: Environment Variables

```powershell
# Server
$env:CLIPBOARD_HOST = "0.0.0.0"
$env:CLIPBOARD_PORT = "5000"

# Client
$env:CLIPBOARD_SERVER = "http://192.168.1.100:5000"

python server.py
```

### Start the server
```powershell
python server.py
# defaults to 0.0.0.0:5000; override with env vars:
# $env:CLIPBOARD_HOST="0.0.0.0"; $env:CLIPBOARD_PORT="5000"; python server.py
```

### Push current clipboard to server
```powershell
# From another terminal
python push_clip.py
# Optional: point to a different host
# $env:CLIPBOARD_SERVER="http://desktop.local:5000"; python push_clip.py
```

### Pull latest clip from server to Windows clipboard
```powershell
python pull_clip.py
```

### API (for iOS Shortcuts)
- `POST /clip` with JSON body:
  - Text: `{"type": "text", "data": "hello", "mime": "text/plain", "source": "phone"}`
  - Image: `{"type": "image", "data": "<base64 png>", "mime": "image/png", "source": "phone"}`
- `GET /clip/latest` returns the stored JSON payload.

Shortcut sketch (Push to server):
1. `Get Clipboard`.
2. If `If` it’s an image → `Convert Image` to PNG → `Base64 Encode`.
3. Build Dictionary with keys `type`, `data`, `mime`, `source`.
4. `Get Contents of URL` (POST) → URL `http://<your-pc-ip>:5000/clip`, Body = JSON (use the dictionary).

Shortcut sketch (Pull from server to phone clipboard):
1. `Get Contents of URL` (GET) → URL `http://<your-pc-ip>:5000/clip/latest`.
2. Parse JSON.
3. If `type` is `text` → `Set Clipboard` to `data`.
4. If `type` is `image` → `Base64 Decode` to file → `Set Clipboard` to that image.

Notes:
- No encryption/auth is applied; keep the server on trusted networks only.
- Images are stored/sent as PNG base64; large images will be larger over the wire.
