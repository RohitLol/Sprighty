# Sprightly

**Sprightly** is a Windows desktop app for mirroring, controlling, and managing your Android phone — built on top of [scrcpy](https://github.com/Genymobile/scrcpy) with a polished dark UI.

> Developed for Pixel 8a · Windows 10/11 · Python 3.12+

---

## Features

| Feature | Description |
|---------|-------------|
| 📱 **Screen Mirror** | Embed the phone screen directly in the app window at a fixed 9:20 ratio |
| 🔌 **USB Connect** | Step-by-step guide to enable USB debugging and auto-detect the device |
| 📡 **WiFi Connect** | Pair & reconnect wirelessly via Android Wireless Debugging (same network) |
| 🔆 **Phone Controls** | Wake screen, Home, Back, Recent Apps from the toolbar |
| 🖱️ **Middle-click Recents** | Middle-click anywhere in the mirror to open Recent Apps |
| 📋 **Clipboard Sync** | Push your PC clipboard to the phone (scrcpy syncs phone→PC automatically) |
| 🌐 **Send URL** | Grab the phone's current browser URL and open it in your PC browser |
| 📁 **File Manager** | Browse `/storage/emulated/0`, sort, view details or grid, drag-drop to push |
| 🖼️ **Photo Browser** | Scans DCIM, Pictures, Screenshots, WhatsApp, Telegram and more |
| 🎨 **Phone Frame** | Pixel 8a-style bezel overlay with punch-hole camera and side buttons |

---

## Requirements

| Requirement | Version |
|-------------|---------|
| Python | 3.12 or newer |
| Windows | 10 / 11 (64-bit) |
| scrcpy | 3.3.4 (bundled separately — see below) |
| Android phone | Android 11+ with USB or Wireless Debugging enabled |

---

## Installation

### 1 — Clone the repo

```bash
git clone https://github.com/RohitLol/Sprightly.git
cd Sprightly
```

### 2 — Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4 — Download scrcpy v3.3.4 (Windows)

Sprightly ships **without** the scrcpy binaries to keep the repo small.  
You need to download them manually and place them in the right folder.

1. Go to the [scrcpy releases page](https://github.com/Genymobile/scrcpy/releases/tag/v3.3.4)
2. Download **`scrcpy-win64-v3.3.4.zip`**
3. Extract the zip — you'll get a folder with `scrcpy.exe`, `adb.exe`, `SDL2.dll`, etc.
4. Rename or move that folder so its contents land at:

```
Sprightly/
└── vendor/
    └── scrcpy/
        ├── scrcpy.exe
        ├── adb.exe
        ├── scrcpy-server
        ├── SDL2.dll
        └── ... (other DLLs)
```

> **Why this version?** scrcpy 3.3.4 includes fixes specifically for Android 16 (Pixel 8a and newer Pixels). Earlier versions may show a black screen.

### 5 — Run

```bash
python main.py
```

---

## Connecting your phone

### USB (simplest)

1. Connect your phone with a **data cable** (not charge-only)
2. Unlock the screen
3. Tap **Allow** on the *"Allow USB debugging?"* prompt
4. The device appears automatically in the device list

> First time? Enable Developer Options first:  
> **Settings → About phone → tap Build number 7×**  
> Then turn on **USB Debugging** inside Developer Options.

### WiFi (wireless, same network only)

Wireless Debugging requires your PC and phone to be on the **same local Wi-Fi network**. It does **not** work over mobile data or between different networks.

1. On your phone: **Settings → Developer Options → Wireless debugging** → turn it ON
2. In Sprightly, click **WiFi** in the toolbar
3. Use the **"Pair new device"** tab:
   - Enter the **IP address** shown at the top of the Wireless debugging page
   - Enter the **Connect Port** (the number next to the IP, e.g. `38291`)
   - Tap **Pair device with pairing code** on your phone
   - Enter the **Pairing Port** and **6-digit code** shown on screen
   - Click **Pair & Connect**
4. Next time you connect, use the **"Reconnect"** tab — just enter IP and port

> **Note:** Wireless Debugging turns off automatically when the screen locks. This is an Android security feature, not a bug.

---

## Project structure

```
Sprightly/
├── main.py                  # Entry point
├── run_debug.py             # Debug launcher with console output
├── requirements.txt
├── app/
│   ├── main_window.py       # QMainWindow + toolbar + tray icon
│   ├── mirror_container.py  # Scrcpy HWND embedding + phone frame overlay
│   ├── file_panel.py        # File browser + photo grid tabs
│   ├── pairing_dialog.py    # WiFi pair & reconnect dialog
│   ├── usb_dialog.py        # USB setup guide dialog
│   ├── settings_dialog.py   # Video quality settings
│   └── style.py             # Global dark QSS stylesheet
├── core/
│   ├── adb_bridge.py        # All adb.exe subprocess wrappers
│   ├── adb_discover.py      # Port auto-detection scanner
│   ├── adb_files.py         # File listing + photo discovery
│   ├── device_manager.py    # QThread device polling + signals
│   ├── scrcpy_launcher.py   # Scrcpy subprocess management
│   ├── settings_store.py    # QSettings persistence
│   └── worker.py            # QThreadPool helper for background tasks
├── models/
│   └── device.py            # Device dataclass (serial, state, transport)
├── utils/
│   ├── icon_loader.py       # SVG icon loader
│   └── vendor_paths.py      # Resolves vendor/scrcpy/ paths at runtime
├── resources/
│   └── icons/               # Material Design SVG icons
└── vendor/
    └── scrcpy/              # ← place scrcpy binaries here (not in git)
```

---

## Keyboard shortcuts & tips

| Action | How |
|--------|-----|
| Open Recent Apps | Middle-click anywhere in the mirror **or** click **Recents** in toolbar |
| Wake screen | Click **Wake** in toolbar |
| Send browser URL to PC | Click **Send URL** (works best while mirror is active) |
| Push clipboard to phone | Copy text on PC → click **Clipboard** |
| Refresh file list | Click **Refresh** in toolbar |

---

## Troubleshooting

**Black screen after starting mirror**  
Run in a terminal: `adb shell rm /data/local/tmp/scrcpy-server.jar`  
Then try mirroring again.

**Device shows as Unauthorized**  
Revoke USB debugging on the phone (Developer Options → Revoke USB debugging authorizations), reconnect the cable, and tap Allow again.

**WiFi auto-detect causes the app to freeze briefly**  
Fixed in the current version — all port-scanning now runs on a background thread.

**App crashes on startup**  
Make sure `vendor/scrcpy/` contains `adb.exe` and `scrcpy.exe`. The app validates these on launch.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `PySide6` | Qt 6 GUI framework |
| `psutil` | Process management |
| `zeroconf` | mDNS (future auto-discovery) |
| `opencv-python` | Image processing for photo grid |

---

## License

MIT — do whatever you want, just don't blame me if it breaks something.
