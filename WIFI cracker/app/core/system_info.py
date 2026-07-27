"""Local adapter / subnet discovery for Windows."""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterInfo:
    name: str
    ip: str
    netmask: str
    gateway: str | None
    subnet: str
    cidr: int
    is_wifi: bool

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(f"{self.ip}/{self.cidr}", strict=False)


def _run(cmd: list[str], timeout: float = 20.0) -> str:
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


def _mask_to_cidr(mask: str) -> int:
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except ValueError:
        return 24


def _ipv4_gateways_from_route() -> list[str]:
    """IPv4 default gateways from `route print -4` (most reliable on Windows)."""
    text = _run(["route", "print", "-4"])
    gateways: list[str] = []
    in_active = False
    for line in text.splitlines():
        if "Active Routes" in line or "Active routes" in line:
            in_active = True
            continue
        if not in_active:
            continue
        if "Persistent Routes" in line:
            break
        # 0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.18     25
        m = re.match(
            r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+([0-9.]+)\s+([0-9.]+)\s+(\d+)",
            line,
        )
        if m:
            gw = m.group(1)
            if gw != "0.0.0.0":
                gateways.append(gw)
    return gateways


def get_primary_adapter() -> AdapterInfo | None:
    """Pick the most useful IPv4 adapter (prefer Wi‑Fi / private LAN)."""
    adapters = list_adapters()
    if not adapters:
        return None

    def score(a: AdapterInfo) -> tuple:
        ip = ipaddress.IPv4Address(a.ip)
        private = int(ip.is_private)
        not_apipa = int(not ip.is_link_local)
        wifi = int(a.is_wifi)
        has_gw = int(bool(a.gateway))
        # Prefer real Wi‑Fi / Ethernet over virtual / Bluetooth
        lower = a.name.lower()
        penalty = 0
        if "virtual" in lower or "bluetooth" in lower or "loopback" in lower:
            penalty = -5
        if "local area connection*" in lower:
            penalty = -5
        return (private, not_apipa, has_gw, wifi, penalty)

    return sorted(adapters, key=score, reverse=True)[0]


def list_adapters() -> list[AdapterInfo]:
    text = _run(["ipconfig", "/all"])
    if not text:
        return _fallback_from_socket()

    # Split on adapter headers: "Wireless LAN adapter Wi-Fi:"
    header_re = re.compile(
        r"^(?P<header>(?:Wireless LAN |Ethernet |PPP |VPN |Tunnel )?adapter (?P<name>[^\r\n:]+):)\s*$",
        re.I | re.M,
    )
    matches = list(header_re.finditer(text))
    route_gateways = _ipv4_gateways_from_route()
    results: list[AdapterInfo] = []

    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]
        name = match.group("name").strip()

        ip_match = re.search(
            r"(?:IPv4 Address|IP Address)[^:]*:\s*([0-9.]+)",
            block,
            re.I,
        )
        mask_match = re.search(r"Subnet Mask[^:]*:\s*([0-9.]+)", block, re.I)
        if not ip_match or not mask_match:
            continue

        ip = ip_match.group(1)
        mask = mask_match.group(1)
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local:
            continue

        # Prefer IPv4 gateway lines inside the block; ignore fe80:: link-local
        gateway = None
        for gw_match in re.finditer(r"Default Gateway[^:]*:\s*([^\s]+)", block, re.I):
            candidate = gw_match.group(1).strip()
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", candidate):
                gateway = candidate
                break

        if gateway is None:
            # Match a route gateway that lives on this subnet
            try:
                net = ipaddress.IPv4Network(f"{ip}/{_mask_to_cidr(mask)}", strict=False)
                for rg in route_gateways:
                    if ipaddress.IPv4Address(rg) in net:
                        gateway = rg
                        break
            except ValueError:
                pass
        if gateway is None and route_gateways:
            gateway = route_gateways[0]

        cidr = _mask_to_cidr(mask)
        header_l = match.group("header").lower()
        name_l = name.lower()
        is_wifi = "wireless" in header_l or "wi-fi" in name_l or "wifi" in name_l
        results.append(
            AdapterInfo(
                name=name,
                ip=ip,
                netmask=mask,
                gateway=gateway,
                subnet=str(ipaddress.IPv4Network(f"{ip}/{cidr}", strict=False).network_address),
                cidr=cidr,
                is_wifi=is_wifi,
            )
        )

    return results or _fallback_from_socket()


def _fallback_from_socket() -> list[AdapterInfo]:
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
    except OSError:
        ip = ""
    if not ip or ip.startswith("127."):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            sock.close()
        except OSError:
            return []
    cidr = 24
    mask = "255.255.255.0"
    gws = _ipv4_gateways_from_route()
    return [
        AdapterInfo(
            name="Primary",
            ip=ip,
            netmask=mask,
            gateway=gws[0] if gws else None,
            subnet=str(ipaddress.IPv4Network(f"{ip}/{cidr}", strict=False).network_address),
            cidr=cidr,
            is_wifi=False,
        )
    ]


def get_local_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"
