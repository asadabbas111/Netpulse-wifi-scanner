"""Nearby Wi‑Fi survey via Windows netsh WLAN."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable


ProgressCallback = Callable[[str, float], None]


@dataclass
class WifiNetwork:
    ssid: str
    bssid: str
    signal: int  # 0–100
    radio: str
    channel: int | None
    auth: str
    encryption: str
    band: str

    @property
    def signal_label(self) -> str:
        if self.signal >= 80:
            quality = "Excellent"
        elif self.signal >= 60:
            quality = "Good"
        elif self.signal >= 40:
            quality = "Fair"
        elif self.signal >= 20:
            quality = "Weak"
        else:
            quality = "Poor"
        return f"{self.signal}% · {quality}"

    def to_row(self) -> tuple:
        return (
            self.ssid or "(hidden)",
            self.bssid,
            self.signal_label,
            str(self.channel) if self.channel is not None else "—",
            self.band,
            self.auth,
            self.encryption,
            self.radio,
        )


def _normalize_band(band: str | None, channel: int | None, radio: str) -> str:
    if band:
        cleaned = band.strip()
        if cleaned:
            return cleaned
    return _channel_to_band(channel, radio)


def _run(cmd: list[str], timeout: float = 30.0) -> str:
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
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout or ""


def _channel_to_band(channel: int | None, radio: str) -> str:
    if channel is None:
        rl = radio.lower()
        if "6" in rl or "ax" in rl and "6ghz" in rl:
            return "6 GHz"
        if "5" in rl:
            return "5 GHz"
        return "2.4 GHz"
    if channel >= 1 and channel <= 14:
        return "2.4 GHz"
    if channel >= 32:
        return "5 GHz"
    return "—"


def scan_wifi_networks(on_progress: ProgressCallback | None = None) -> list[WifiNetwork]:
    """Trigger a WLAN scan and parse `netsh wlan show networks mode=bssid`."""
    if on_progress:
        on_progress("Requesting Windows WLAN scan…", 0.1)

    # Refresh scan (best effort; Windows may throttle)
    _run(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=25.0)

    if on_progress:
        on_progress("Parsing nearby access points…", 0.55)

    text = _run(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=25.0)
    if not text.strip():
        if on_progress:
            on_progress("No Wi‑Fi data (adapter off or no WLAN interface).", 1.0)
        return []

    networks: list[WifiNetwork] = []
    current_ssid = ""
    current_auth = ""
    current_cipher = ""
    pending: dict | None = None

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        channel = pending.get("channel")
        radio = pending.get("radio") or ""
        networks.append(
            WifiNetwork(
                ssid=pending.get("ssid") or current_ssid,
                bssid=pending.get("bssid") or "—",
                signal=int(pending.get("signal") or 0),
                radio=radio or "—",
                channel=channel,
                auth=pending.get("auth") or current_auth or "—",
                encryption=pending.get("cipher") or current_cipher or "—",
                band=_normalize_band(pending.get("band"), channel, radio),
            )
        )
        pending = None

    for raw in text.splitlines():
        line = raw.rstrip()
        # SSID lines only — never match BSSID
        ssid_m = re.match(r"^\s*SSID\s+\d+\s*:\s*(.*)$", line, re.I)
        if ssid_m:
            flush()
            current_ssid = ssid_m.group(1).strip()
            continue

        auth_m = re.match(r"^\s*Authentication\s*:\s*(.*)$", line, re.I)
        if auth_m:
            current_auth = auth_m.group(1).strip()
            continue

        cipher_m = re.match(r"^\s*Encryption\s*:\s*(.*)$", line, re.I)
        if cipher_m:
            current_cipher = cipher_m.group(1).strip()
            continue

        bssid_m = re.match(
            r"^\s*BSSID\s+\d+\s*:\s*([0-9A-Fa-f:\-]+)\s*$",
            line,
            re.I,
        )
        if bssid_m:
            flush()
            pending = {
                "ssid": current_ssid,
                "bssid": bssid_m.group(1).upper().replace("-", ":"),
                "auth": current_auth,
                "cipher": current_cipher,
            }
            continue

        if pending is None:
            continue

        sig_m = re.match(r"^\s*Signal\s*:\s*(\d+)\s*%", line, re.I)
        if sig_m:
            pending["signal"] = int(sig_m.group(1))
            continue

        radio_m = re.match(r"^\s*Radio type\s*:\s*(.*)$", line, re.I)
        if radio_m:
            pending["radio"] = radio_m.group(1).strip()
            continue

        band_m = re.match(r"^\s*Band\s*:\s*(.*)$", line, re.I)
        if band_m:
            pending["band"] = band_m.group(1).strip()
            continue

        ch_m = re.match(r"^\s*Channel\s*:\s*(\d+)\s*$", line, re.I)
        if ch_m:
            pending["channel"] = int(ch_m.group(1))
            continue

    flush()

    # Deduplicate by BSSID, keep strongest signal
    best: dict[str, WifiNetwork] = {}
    for net in networks:
        key = net.bssid.upper()
        prev = best.get(key)
        if prev is None or net.signal > prev.signal:
            best[key] = net

    result = sorted(best.values(), key=lambda n: (-n.signal, n.ssid.lower()))
    if on_progress:
        on_progress(f"Found {len(result)} access point(s).", 1.0)
    return result


def get_connected_ssid() -> str | None:
    text = _run(["netsh", "wlan", "show", "interfaces"], timeout=10.0)
    m = re.search(r"^\s*SSID\s*:\s*(.+)\s*$", text, re.M | re.I)
    if not m:
        return None
    ssid = m.group(1).strip()
    if not ssid or ssid.lower() == "ssid":
        return None
    # Avoid matching BSSID line accidentally — netsh uses "SSID" and "BSSID" separately
    state = re.search(r"^\s*State\s*:\s*(.+)\s*$", text, re.M | re.I)
    if state and "connected" not in state.group(1).lower():
        return None
    return ssid
