"""Recover Wi‑Fi passwords from Windows saved WLAN profiles only.

This does NOT crack nearby networks. It only reads credentials Windows
already stores for networks this PC has joined (requires appropriate rights).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable


ProgressCallback = Callable[[str, float], None]


@dataclass
class SavedWifiProfile:
    name: str
    auth: str
    encryption: str
    password: str | None
    key_visible: bool
    notes: str = ""

    def to_row(self) -> tuple:
        if self.password:
            secret = self.password
        elif not self.key_visible:
            secret = "(run as Admin to reveal)"
        else:
            secret = "(none / open network)"
        return (self.name, self.auth, self.encryption, secret, self.notes)


def _run(cmd: list[str], timeout: float = 20.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    out = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, out


def list_profile_names() -> list[str]:
    code, text = _run(["netsh", "wlan", "show", "profiles"])
    if code != 0 and not text:
        return []
    names: list[str] = []
    for line in text.splitlines():
        m = re.search(r"All User Profile\s*:\s*(.+)\s*$", line, re.I)
        if not m:
            m = re.search(r"User Profile\s*:\s*(.+)\s*$", line, re.I)
        if m:
            name = m.group(1).strip()
            if name:
                names.append(name)
    return names


def get_profile_details(name: str) -> SavedWifiProfile:
    code, text = _run(["netsh", "wlan", "show", "profile", f"name={name}", "key=clear"])
    auth = _first(text, r"Authentication\s*:\s*(.+)")
    encryption = _first(text, r"Cipher\s*:\s*(.+)") or _first(text, r"Security key\s*:\s*(.+)")
    # Prefer "Key Content"
    password = _first(text, r"Key Content\s*:\s*(.+)")
    key_present = _first(text, r"Security key\s*:\s*(.+)")

    notes = ""
    key_visible = True
    if password is None:
        if code != 0 or "Key Content" not in text:
            # Often requires elevation
            if key_present and key_present.lower() in ("present", "yes"):
                key_visible = False
                notes = "Key stored — elevate NetPulse to view"
            elif "not found" in text.lower():
                notes = "Profile not found"
            else:
                key_visible = False
                notes = "Password hidden (try Run as Administrator)"
        else:
            notes = "Open / no passphrase"

    return SavedWifiProfile(
        name=name,
        auth=auth or "—",
        encryption=encryption or "—",
        password=password,
        key_visible=key_visible if password is None else True,
        notes=notes,
    )


def load_saved_profiles(on_progress: ProgressCallback | None = None) -> list[SavedWifiProfile]:
    if on_progress:
        on_progress("Listing Windows WLAN profiles…", 0.1)
    names = list_profile_names()
    if not names:
        if on_progress:
            on_progress("No saved Wi‑Fi profiles on this PC.", 1.0)
        return []

    profiles: list[SavedWifiProfile] = []
    for i, name in enumerate(names):
        if on_progress:
            on_progress(f"Reading profile “{name}”…", 0.1 + 0.9 * ((i + 1) / len(names)))
        profiles.append(get_profile_details(name))
    return profiles


def password_for_ssid(ssid: str) -> SavedWifiProfile | None:
    """Return saved profile matching SSID (case-insensitive), if any."""
    target = ssid.strip().lower()
    for name in list_profile_names():
        if name.strip().lower() == target:
            return get_profile_details(name)
    return None


def nearest_saved_password(
    networks: list,
) -> tuple | None:
    """Among nearby APs, find the strongest signal whose SSID is saved locally.

    Returns (WifiNetwork, SavedWifiProfile) or None.
    """
    from app.core.wifi_scanner import WifiNetwork  # local import for typing softness

    saved = {n.strip().lower(): n for n in list_profile_names()}
    for net in sorted(networks, key=lambda n: -n.signal):
        if not isinstance(net, WifiNetwork):
            continue
        key = (net.ssid or "").strip().lower()
        if key and key in saved:
            return net, get_profile_details(saved[key])
    return None


def _first(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.I | re.M)
    if not m:
        return None
    value = m.group(1).strip()
    return value or None
