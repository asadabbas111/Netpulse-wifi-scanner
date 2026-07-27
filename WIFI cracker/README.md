# NetPulse

Professional Windows GUI tool for LAN device discovery, nearby Wi‑Fi survey, and viewing **saved** Wi‑Fi passwords on this PC.

---

## What you need before running

| Requirement | Details |
|-------------|---------|
| **Operating system** | Windows 10 or Windows 11 |
| **Python** | **3.10 or newer** (3.11 / 3.12 / 3.13 all work) |
| **pip** | Comes with Python if “Add python.exe to PATH” is checked |
| **Network** | Connected to a LAN (Wi‑Fi or Ethernet) for device scanning |
| **Wi‑Fi adapter** | Required for Wi‑Fi Survey and Saved Passwords tabs |
| **Admin (optional)** | Recommended so saved Wi‑Fi keys are fully visible |

NetPulse does **not** need Node.js, Docker, or a database.

---

## 1. Install Python (if you don’t have it)

1. Download Python from: [https://www.python.org/downloads/](https://www.python.org/downloads/)
2. Run the installer.
3. **Important:** enable **“Add python.exe to PATH”**.
4. Finish install, then open a **new** PowerShell or Command Prompt and check:

```powershell
python --version
```

You should see something like `Python 3.13.x` (any **3.10+** is fine).

If `python` is not found, try:

```powershell
py --version
```

---

## 2. Go to the project folder

Open PowerShell and change into the folder where the project is saved:

```powershell
cd "(enter file path)"
```

Example shape (use your own path):

```powershell
cd "C:\Users\...\Documents\YourProjectFolder"
```

If the path has spaces, always keep the quotes around it.

---

## 3. Easiest way to run (recommended)

Inside the project folder, double‑click:

```text
run.bat
```

That script will:

1. Check that Python is installed  
2. Create a virtual environment (`.venv`) the first time  
3. Install dependencies from `requirements.txt`  
4. Launch the NetPulse GUI  

---

## 4. Manual install & run (PowerShell)

Use these commands every time you set up the project in a **new folder** (or after copying the project):

```powershell
cd "(enter file path)"

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

### What each step does

| Command | Purpose |
|---------|---------|
| `cd "(enter file path)"` | Open the project folder |
| `python -m venv .venv` | Create a local virtual environment |
| `.\.venv\Scripts\Activate.ps1` | Activate that environment |
| `python -m pip install --upgrade pip` | Update pip |
| `pip install -r requirements.txt` | Install CustomTkinter, Pillow, etc. |
| `python main.py` | Start the GUI |

### If activation is blocked by policy

Run once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then run `.\.venv\Scripts\Activate.ps1` again.

### Command Prompt (cmd) instead of PowerShell

```cmd
cd "(enter file path)"
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

### After the first setup (later sessions)

If `.venv` already exists:

```powershell
cd "(enter file path)"
.\.venv\Scripts\Activate.ps1
python main.py
```

---

## 5. Python packages (dependencies)

Installed from `requirements.txt`:

| Package | Why it’s needed |
|---------|-----------------|
| **customtkinter** | Modern dark GUI (buttons, tabs, layout) |
| **Pillow** | Image support used by CustomTkinter |
| **darkdetect** | Pulled in by CustomTkinter (theme helpers) |
| **packaging** | Pulled in by CustomTkinter |

Standard library modules used (no install needed): `subprocess`, `socket`, `threading`, `ipaddress`, `tkinter` (bundled with official Python on Windows).

---

## 6. Run as Administrator (optional but useful)

To reveal all saved Wi‑Fi passwords:

1. Right‑click **Command Prompt** or **PowerShell** → **Run as administrator**
2. Then:

```powershell
cd "(enter file path)"
.\.venv\Scripts\Activate.ps1
python main.py
```

Or right‑click `run.bat` → **Run as administrator**.

---

## Features (what each tab does)

### Devices
- Scans your local subnet for connected devices  
- Shows IP, hostname, MAC, vendor, latency, role (This PC / Gateway / Host)  
- **Refresh Adapter** — reloads your current IP/subnet/gateway/SSID (does not scan devices)  
- **Export CSV** — saves the device list  

### Wi‑Fi Survey
- Lists nearby access points (SSID, BSSID, signal, channel, band, security)  
- **Nearest Saved Key** — password only if that SSID is already saved on this Windows PC  

### Saved Passwords
- Reads Windows WLAN profiles you previously joined  
- **Copy Password** — copies the selected key to the clipboard  

---

## Legal / scope note

| Action | Supported |
|--------|-----------|
| List nearby Wi‑Fi networks | Yes |
| Show passwords for networks **saved on this PC** | Yes |
| Crack / recover passwords for unknown nearby Wi‑Fi | **No** |

Use only on networks you own or are authorized to manage.

---

## Project structure

```text
netpulse/
├── main.py                 # Entry point — start the GUI
├── requirements.txt        # Python dependencies
├── run.bat                 # One-click setup + launch (Windows)
├── README.md               # This file
├── .gitignore
└── app/
    ├── __init__.py
    ├── core/
    │   ├── system_info.py      # Detect adapter / subnet / gateway
    │   ├── network_scanner.py  # LAN device scan (ping + ARP)
    │   ├── wifi_scanner.py     # Nearby Wi‑Fi via netsh
    │   ├── wifi_passwords.py   # Saved Windows WLAN profiles
    │   └── oui.py              # MAC vendor lookup
    └── gui/
        ├── main_window.py      # Main CustomTkinter UI
        └── theme.py            # Colors / fonts
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'customtkinter'`
The project was opened without installing packages (common after copying to a new folder). Run:

```powershell
cd "(enter file path)"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

### `python` is not recognized
- Reinstall Python and enable **Add to PATH**, or use `py -3` instead of `python`.

### `Activate.ps1` cannot be loaded (execution policy)
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### GUI does not open / tkinter error
- Reinstall Python from python.org (the Microsoft Store build sometimes omits `tkinter`).
- Confirm: `python -c "import tkinter; print('ok')"`.

### `pip install` fails (network / SSL)
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Wi‑Fi Survey shows no networks
- Turn Wi‑Fi on in Windows settings.  
- Make sure you are not on Ethernet-only with Wi‑Fi radio disabled.

### Passwords show as hidden
- Run NetPulse **as Administrator**.  
- Only profiles already saved on this PC can be shown.

### Device scan finds few hosts
- Some devices ignore ping; they may still appear as **ARP only** after traffic.  
- Confirm **Refresh Adapter** shows the correct subnet before scanning.  
- Private/guest Wi‑Fi networks may isolate clients from each other.

### Antivirus warning
- Scanning the LAN uses normal Windows `ping` / `arp` / `netsh` commands. Allow the app if your AV prompts.

---

## Quick checklist

- [ ] Windows 10/11  
- [ ] Python 3.10+ installed and on PATH  
- [ ] Opened the project with `cd "(enter file path)"`  
- [ ] Ran `run.bat` **or** created `.venv` and installed `requirements.txt`  
- [ ] Launched with `python main.py`  
- [ ] (Optional) Ran as Administrator for full saved Wi‑Fi keys  

---

## Version

NetPulse **1.0.0** — Windows desktop GUI.
