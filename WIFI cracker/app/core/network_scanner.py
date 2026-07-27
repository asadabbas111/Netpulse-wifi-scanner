"""LAN host discovery via ICMP probe + ARP table correlation."""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from app.core.oui import lookup_vendor
from app.core.system_info import AdapterInfo


ProgressCallback = Callable[[str, float], None]
DeviceCallback = Callable[["Device"], None]


@dataclass
class Device:
    ip: str
    mac: str | None = None
    hostname: str | None = None
    vendor: str = "Unknown"
    latency_ms: float | None = None
    is_gateway: bool = False
    is_self: bool = False
    status: str = "Online"
    notes: list[str] = field(default_factory=list)

    def to_row(self) -> tuple:
        return (
            self.ip,
            self.hostname or "—",
            self.mac or "—",
            self.vendor,
            f"{self.latency_ms:.0f} ms" if self.latency_ms is not None else "—",
            self.role_label,
            self.status,
        )

    @property
    def role_label(self) -> str:
        if self.is_self:
            return "This PC"
        if self.is_gateway:
            return "Gateway"
        return "Host"


def _run(cmd: list[str], timeout: float = 15.0) -> str:
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
    return (completed.stdout or "") + (completed.stderr or "")


def _ping(ip: str, timeout_ms: int = 800) -> float | None:
    """Return RTT ms if host replies, else None."""
    # Windows: ping -n 1 -w <ms>
    out = _run(["ping", "-n", "1", "-w", str(timeout_ms), ip], timeout=(timeout_ms / 1000.0) + 2.0)
    if not out:
        return None
    if re.search(r"TTL[=|:]|time[=<]", out, re.I):
        m = re.search(r"time[=<]\s*(\d+)\s*ms", out, re.I)
        if m:
            return float(m.group(1))
        if "time<" in out.lower():
            return 1.0
        return 0.0
    return None


def _resolve_hostname(ip: str) -> str | None:
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        if name and name != ip:
            return name.split(".")[0] if name.endswith(".local") else name
    except (socket.herror, socket.gaierror, OSError):
        pass

    # NetBIOS-style (Windows nbtstat) — best effort, may be slow
    out = _run(["nbtstat", "-A", ip], timeout=3.0)
    m = re.search(r"^\s*([^\s]+)\s+<00>\s+UNIQUE", out, re.M | re.I)
    if m:
        name = m.group(1).strip()
        if name and name.upper() != "NAME":
            return name
    return None


def parse_arp_table() -> dict[str, str]:
    """Map IP → MAC from `arp -a`."""
    out = _run(["arp", "-a"], timeout=10.0)
    mapping: dict[str, str] = {}
    for line in out.splitlines():
        m = re.search(
            r"^\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)\s+([0-9a-fA-F\-:]{11,17})\s+\w+",
            line,
        )
        if not m:
            continue
        ip, mac = m.group(1), m.group(2)
        if mac.lower().replace("-", "") in ("000000000000", "ffffffffffff"):
            continue
        # Normalize to AA:BB:CC:DD:EE:FF
        hex_only = re.sub(r"[^0-9A-Fa-f]", "", mac)
        if len(hex_only) != 12:
            continue
        pretty = ":".join(hex_only[i : i + 2] for i in range(0, 12, 2)).upper()
        mapping[ip] = pretty
    return mapping


def _get_own_mac(ip: str) -> str | None:
    """Try to resolve this machine's MAC for the given IPv4."""
    out = _run(["getmac", "/v", "/fo", "csv", "/nh"], timeout=8.0)
    # Fallback: PowerShell not required — parse ipconfig /all Physical Address near IPv4
    text = _run(["ipconfig", "/all"], timeout=10.0)
    blocks = re.split(r"\r?\n\r?\n", text)
    for block in blocks:
        if ip not in block:
            continue
        m = re.search(r"Physical Address[^:]*:\s*([0-9A-Fa-f\-]+)", block)
        if m:
            hex_only = re.sub(r"[^0-9A-Fa-f]", "", m.group(1))
            if len(hex_only) == 12:
                return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2)).upper()
    _ = out
    return None


class NetworkScanner:
    def __init__(
        self,
        adapter: AdapterInfo,
        max_workers: int = 64,
        ping_timeout_ms: int = 700,
    ) -> None:
        self.adapter = adapter
        self.max_workers = max_workers
        self.ping_timeout_ms = ping_timeout_ms
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def scan(
        self,
        on_progress: ProgressCallback | None = None,
        on_device: DeviceCallback | None = None,
    ) -> list[Device]:
        self._cancel.clear()
        network = self.adapter.network
        hosts = [str(h) for h in network.hosts()]
        # Cap very large subnets (e.g. /16) to keep UI responsive
        if len(hosts) > 1024:
            # Prefer gateway neighborhood: scan /24 around our IP
            local = ipaddress.IPv4Address(self.adapter.ip)
            base = ipaddress.IPv4Network(f"{local}/24", strict=False)
            hosts = [str(h) for h in base.hosts()]
            if on_progress:
                on_progress("Subnet is large — scanning /24 around this PC for accuracy.", 0.02)

        total = len(hosts)
        alive: dict[str, float] = {}
        done = 0
        lock = threading.Lock()

        def probe(ip: str) -> None:
            nonlocal done
            if self._cancel.is_set():
                return
            rtt = _ping(ip, self.ping_timeout_ms)
            with lock:
                if rtt is not None:
                    alive[ip] = rtt
                done += 1
                if on_progress and done % 8 == 0:
                    on_progress(f"Probing hosts… {done}/{total}", 0.05 + 0.55 * (done / total))

        if on_progress:
            on_progress(f"Scanning {network} ({total} addresses)…", 0.05)

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(probe, ip) for ip in hosts]
            for fut in as_completed(futures):
                if self._cancel.is_set():
                    break
                _ = fut.exception()

        if self._cancel.is_set():
            if on_progress:
                on_progress("Scan cancelled.", 1.0)
            return []

        # Always include self
        alive.setdefault(self.adapter.ip, 0.0)
        if self.adapter.gateway:
            # Gateway may not answer ICMP; still try to keep it
            pass

        if on_progress:
            on_progress("Reading ARP table…", 0.65)
        # Brief pause so Windows ARP cache settles after flood of pings
        time.sleep(0.35)
        arp = parse_arp_table()

        own_mac = _get_own_mac(self.adapter.ip)
        if own_mac:
            arp[self.adapter.ip] = own_mac

        devices: list[Device] = []
        targets = set(alive.keys()) | set(
            ip for ip in arp if _ip_in_network(ip, network)
        )
        if self.adapter.gateway:
            targets.add(self.adapter.gateway)

        resolved = 0
        target_list = sorted(targets, key=lambda x: tuple(int(p) for p in x.split(".")))
        for ip in target_list:
            if self._cancel.is_set():
                break
            mac = arp.get(ip)
            hostname = _resolve_hostname(ip)
            vendor = lookup_vendor(mac)
            rtt = alive.get(ip)
            status = "Online" if ip in alive or ip == self.adapter.ip else "ARP only"
            device = Device(
                ip=ip,
                mac=mac,
                hostname=hostname,
                vendor=vendor,
                latency_ms=rtt,
                is_gateway=(ip == self.adapter.gateway),
                is_self=(ip == self.adapter.ip),
                status=status,
            )
            devices.append(device)
            if on_device:
                on_device(device)
            resolved += 1
            if on_progress:
                on_progress(
                    f"Resolving hosts… {resolved}/{len(target_list)}",
                    0.65 + 0.35 * (resolved / max(len(target_list), 1)),
                )

        devices.sort(
            key=lambda d: (
                not d.is_self,
                not d.is_gateway,
                tuple(int(p) for p in d.ip.split(".")),
            )
        )
        if on_progress:
            on_progress(f"Found {len(devices)} device(s).", 1.0)
        return devices


def _ip_in_network(ip: str, network: ipaddress.IPv4Network) -> bool:
    try:
        return ipaddress.IPv4Address(ip) in network
    except ValueError:
        return False
