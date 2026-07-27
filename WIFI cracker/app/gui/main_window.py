"""NetPulse main window — LAN devices, Wi‑Fi survey, saved credentials."""

from __future__ import annotations

import csv
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from app import __app_name__, __version__
from app.core.network_scanner import Device, NetworkScanner
from app.core.system_info import AdapterInfo, get_local_hostname, get_primary_adapter
from app.core.wifi_passwords import (
    SavedWifiProfile,
    load_saved_profiles,
    nearest_saved_password,
    password_for_ssid,
)
from app.core.wifi_scanner import WifiNetwork, get_connected_ssid, scan_wifi_networks
from app.gui.theme import COLORS, FONTS


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class NetPulseApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{__app_name__}  ·  Network Intelligence")
        self.geometry("1180x720")
        self.minsize(980, 620)
        self.configure(fg_color=COLORS["bg"])

        self.adapter: AdapterInfo | None = get_primary_adapter()
        self._devices: list[Device] = []
        self._wifi: list[WifiNetwork] = []
        self._profiles: list[SavedWifiProfile] = []
        self._scanner: NetworkScanner | None = None
        self._busy = False

        self._build_style()
        self._build_layout()
        self._refresh_header_stats()
        self.after(200, self._startup_hint)

    # ------------------------------------------------------------------ UI
    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Net.Treeview",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            fieldbackground=COLORS["surface"],
            borderwidth=0,
            rowheight=28,
            font=FONTS["mono_small"],
        )
        style.configure(
            "Net.Treeview.Heading",
            background=COLORS["header"],
            foreground=COLORS["muted"],
            relief="flat",
            font=FONTS["ui_small"],
        )
        style.map(
            "Net.Treeview",
            background=[("selected", COLORS["accent_dim"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.map(
            "Net.Treeview.Heading",
            background=[("active", COLORS["surface_alt"])],
        )

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=88)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        header.grid_propagate(False)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, padx=22, pady=16, sticky="w")
        ctk.CTkLabel(
            brand,
            text=__app_name__,
            font=FONTS["brand"],
            text_color=COLORS["accent"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand,
            text="LAN discovery  ·  Wi‑Fi survey  ·  saved credentials",
            font=FONTS["ui_small"],
            text_color=COLORS["muted"],
        ).pack(anchor="w")

        self.stats_label = ctk.CTkLabel(
            header,
            text="",
            font=FONTS["mono_small"],
            text_color=COLORS["muted"],
            justify="right",
        )
        self.stats_label.grid(row=0, column=1, padx=20, pady=16, sticky="e")

        # Body
        body = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        self.tabview = ctk.CTkTabview(
            body,
            fg_color=COLORS["surface"],
            segmented_button_fg_color=COLORS["surface_alt"],
            segmented_button_selected_color=COLORS["accent_dim"],
            segmented_button_selected_hover_color=COLORS["accent"],
            segmented_button_unselected_color=COLORS["surface_alt"],
            segmented_button_unselected_hover_color=COLORS["border"],
            text_color=COLORS["text"],
            corner_radius=10,
        )
        self.tabview.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        body.grid_rowconfigure(0, weight=1)

        self.tab_devices = self.tabview.add("Devices")
        self.tab_wifi = self.tabview.add("Wi‑Fi Survey")
        self.tab_creds = self.tabview.add("Saved Passwords")

        self._build_devices_tab()
        self._build_wifi_tab()
        self._build_creds_tab()

        # Status bar
        status = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0, height=46)
        status.grid(row=2, column=0, sticky="ew")
        status.grid_columnconfigure(0, weight=1)
        status.grid_propagate(False)

        self.progress = ctk.CTkProgressBar(
            status,
            height=6,
            progress_color=COLORS["accent"],
            fg_color=COLORS["border"],
        )
        self.progress.grid(row=0, column=0, sticky="ew", padx=16, pady=(8, 0))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            status,
            text=f"Ready  ·  v{__version__}",
            font=FONTS["ui_small"],
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=16, pady=(2, 8))

    def _toolbar(self, parent: ctk.CTkFrame, buttons: list[tuple[str, Callable[[], None]]]) -> None:
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=12, pady=(12, 8))
        for i, (label, cmd) in enumerate(buttons):
            primary = i == 0
            btn = ctk.CTkButton(
                bar,
                text=label,
                command=cmd,
                width=140,
                height=34,
                corner_radius=8,
                fg_color=COLORS["accent"] if primary else COLORS["surface_alt"],
                hover_color=COLORS["accent_hover"] if primary else COLORS["border"],
                text_color=COLORS["bg"] if primary else COLORS["text"],
                font=FONTS["ui"],
            )
            btn.pack(side="left", padx=(0, 8))

    def _tree_frame(self, parent: ctk.CTkFrame, columns: list[tuple[str, str, int]]) -> ttk.Treeview:
        wrap = ctk.CTkFrame(parent, fg_color=COLORS["surface_alt"], corner_radius=8)
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        cols = [c[0] for c in columns]
        tree = ttk.Treeview(
            wrap,
            columns=cols,
            show="headings",
            style="Net.Treeview",
            selectmode="browse",
        )
        for key, heading, width in columns:
            tree.heading(key, text=heading)
            tree.column(key, width=width, minwidth=60, anchor="w")

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        vsb.pack(side="right", fill="y", pady=1)
        tree.tag_configure("odd", background=COLORS["row_alt"])
        tree.tag_configure("even", background=COLORS["surface"])
        tree.tag_configure("self", foreground=COLORS["accent"])
        tree.tag_configure("gateway", foreground=COLORS["warning"])
        return tree

    def _build_devices_tab(self) -> None:
        self.tab_devices.grid_columnconfigure(0, weight=1)
        self._toolbar(
            self.tab_devices,
            [
                ("Scan Network", self.start_device_scan),
                ("Stop", self.stop_device_scan),
                ("Export CSV", lambda: self._export_csv("devices")),
                ("Refresh Adapter", self._refresh_header_stats),
            ],
        )
        self.device_meta = ctk.CTkLabel(
            self.tab_devices,
            text="Discover hosts on your local subnet (ICMP + ARP).",
            font=FONTS["ui_small"],
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.device_meta.pack(fill="x", padx=14, pady=(0, 6))
        self.device_tree = self._tree_frame(
            self.tab_devices,
            [
                ("ip", "IP Address", 130),
                ("host", "Hostname", 160),
                ("mac", "MAC Address", 150),
                ("vendor", "Vendor", 140),
                ("rtt", "Latency", 90),
                ("role", "Role", 90),
                ("status", "Status", 90),
            ],
        )

    def _build_wifi_tab(self) -> None:
        self._toolbar(
            self.tab_wifi,
            [
                ("Scan Wi‑Fi", self.start_wifi_scan),
                ("Nearest Saved Key", self.show_nearest_saved_key),
                ("Export CSV", lambda: self._export_csv("wifi")),
            ],
        )
        notice = ctk.CTkLabel(
            self.tab_wifi,
            text=(
                "Lists nearby networks from Windows WLAN. "
                "“Nearest Saved Key” only reveals a password if that SSID is already saved on this PC — "
                "NetPulse cannot crack unknown Wi‑Fi passwords."
            ),
            font=FONTS["ui_small"],
            text_color=COLORS["warning"],
            wraplength=1000,
            justify="left",
            anchor="w",
        )
        notice.pack(fill="x", padx=14, pady=(0, 6))
        self.wifi_tree = self._tree_frame(
            self.tab_wifi,
            [
                ("ssid", "SSID", 180),
                ("bssid", "BSSID", 150),
                ("signal", "Signal", 140),
                ("ch", "Channel", 70),
                ("band", "Band", 80),
                ("auth", "Auth", 120),
                ("enc", "Encryption", 100),
                ("radio", "Radio", 100),
            ],
        )
        self.wifi_tree.bind("<Double-1>", self._on_wifi_double_click)

    def _build_creds_tab(self) -> None:
        self._toolbar(
            self.tab_creds,
            [
                ("Load Saved Profiles", self.start_load_profiles),
                ("Copy Password", self.copy_selected_password),
                ("Export CSV", lambda: self._export_csv("creds")),
            ],
        )
        ctk.CTkLabel(
            self.tab_creds,
            text=(
                "Shows passwords Windows already stored for networks you have joined. "
                "Run as Administrator if keys show as hidden."
            ),
            font=FONTS["ui_small"],
            text_color=COLORS["muted"],
            wraplength=1000,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 6))
        self.cred_tree = self._tree_frame(
            self.tab_creds,
            [
                ("name", "Profile / SSID", 200),
                ("auth", "Authentication", 140),
                ("enc", "Encryption", 120),
                ("pass", "Password", 200),
                ("notes", "Notes", 260),
            ],
        )

    # -------------------------------------------------------------- helpers
    def _startup_hint(self) -> None:
        if self.adapter is None:
            self._set_status("No active IPv4 adapter detected.", warn=True)
        else:
            self._set_status(
                f"Adapter ready: {self.adapter.name} · {self.adapter.ip}/{self.adapter.cidr}"
            )

    def _refresh_header_stats(self) -> None:
        self.adapter = get_primary_adapter()
        host = get_local_hostname()
        connected = get_connected_ssid()
        if self.adapter:
            wifi_bit = "Wi‑Fi" if self.adapter.is_wifi else "Ethernet"
            gw = self.adapter.gateway or "—"
            ssid_bit = f"  ·  SSID {connected}" if connected else ""
            self.stats_label.configure(
                text=(
                    f"{host}\n"
                    f"{wifi_bit}  {self.adapter.ip}/{self.adapter.cidr}  ·  GW {gw}{ssid_bit}"
                )
            )
            self.device_meta.configure(
                text=(
                    f"Subnet {self.adapter.network}  ·  adapter “{self.adapter.name}”  ·  "
                    "ICMP probe + ARP correlation"
                )
            )
        else:
            self.stats_label.configure(text="No adapter\n—")

    def _set_status(self, text: str, warn: bool = False) -> None:
        color = COLORS["warning"] if warn else COLORS["muted"]
        self.status_label.configure(text=text, text_color=color)

    def _set_progress(self, value: float) -> None:
        self.progress.set(max(0.0, min(1.0, value)))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _fill_tree(self, tree: ttk.Treeview, rows: list[tuple], special: dict | None = None) -> None:
        tree.delete(*tree.get_children())
        special = special or {}
        for i, row in enumerate(rows):
            tags = ["odd" if i % 2 else "even"]
            extra = special.get(i)
            if extra:
                tags.append(extra)
            tree.insert("", "end", values=row, tags=tuple(tags))

    # ----------------------------------------------------------- device scan
    def start_device_scan(self) -> None:
        if self._busy:
            messagebox.showinfo(__app_name__, "A scan is already running.")
            return
        self._refresh_header_stats()
        if self.adapter is None:
            messagebox.showerror(__app_name__, "No usable network adapter found.")
            return

        self._set_busy(True)
        self._devices.clear()
        self.device_tree.delete(*self.device_tree.get_children())
        self._set_progress(0)
        self._set_status("Starting LAN scan…")

        scanner = NetworkScanner(self.adapter)
        self._scanner = scanner

        def worker() -> None:
            def on_progress(msg: str, frac: float) -> None:
                self.after(0, lambda: (self._set_status(msg), self._set_progress(frac)))

            def on_device(dev: Device) -> None:
                self.after(0, lambda d=dev: self._append_device(d))

            try:
                devices = scanner.scan(on_progress=on_progress, on_device=on_device)
                self.after(0, lambda: self._finish_device_scan(devices))
            except Exception as exc:  # noqa: BLE001 — surface to UI
                self.after(0, lambda: self._fail(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _append_device(self, device: Device) -> None:
        # Avoid duplicates when streaming
        for i, existing in enumerate(self._devices):
            if existing.ip == device.ip:
                self._devices[i] = device
                break
        else:
            self._devices.append(device)
        self._render_devices()

    def _render_devices(self) -> None:
        rows = [d.to_row() for d in self._devices]
        special = {}
        for i, d in enumerate(self._devices):
            if d.is_self:
                special[i] = "self"
            elif d.is_gateway:
                special[i] = "gateway"
        self._fill_tree(self.device_tree, rows, special)

    def _finish_device_scan(self, devices: list[Device]) -> None:
        self._devices = devices
        self._render_devices()
        self._set_busy(False)
        self._scanner = None
        self._set_progress(1)
        self._set_status(f"LAN scan complete — {len(devices)} device(s).")

    def stop_device_scan(self) -> None:
        if self._scanner:
            self._scanner.cancel()
            self._set_status("Cancelling scan…", warn=True)

    # ------------------------------------------------------------- wifi scan
    def start_wifi_scan(self) -> None:
        if self._busy:
            messagebox.showinfo(__app_name__, "A scan is already running.")
            return
        self._set_busy(True)
        self._wifi.clear()
        self.wifi_tree.delete(*self.wifi_tree.get_children())
        self._set_progress(0)
        self._set_status("Scanning nearby Wi‑Fi…")

        def worker() -> None:
            def on_progress(msg: str, frac: float) -> None:
                self.after(0, lambda: (self._set_status(msg), self._set_progress(frac)))

            try:
                nets = scan_wifi_networks(on_progress=on_progress)
                self.after(0, lambda: self._finish_wifi_scan(nets))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._fail(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_wifi_scan(self, nets: list[WifiNetwork]) -> None:
        self._wifi = nets
        self._fill_tree(self.wifi_tree, [n.to_row() for n in nets])
        self._set_busy(False)
        self._set_progress(1)
        connected = get_connected_ssid()
        extra = f"  ·  connected to “{connected}”" if connected else ""
        self._set_status(f"Wi‑Fi survey complete — {len(nets)} AP(s){extra}.")
        self._refresh_header_stats()

    def show_nearest_saved_key(self) -> None:
        """Strongest nearby AP that is already saved on this PC."""
        if self._busy:
            return

        def worker() -> None:
            self.after(0, lambda: self._set_status("Looking up nearest saved network…"))
            nets = self._wifi or scan_wifi_networks()
            if not nets:
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        __app_name__,
                        "No nearby Wi‑Fi networks found. Enable Wi‑Fi and try Scan Wi‑Fi first.",
                    ),
                )
                return
            match = nearest_saved_password(nets)
            if not match:
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        __app_name__,
                        "None of the nearby networks have a password saved on this PC.\n\n"
                        "NetPulse can only show passwords for Wi‑Fi profiles Windows already stored "
                        "(networks you previously joined). It cannot recover passwords for unknown networks.",
                    ),
                )
                return
            net, profile = match
            pwd = profile.password or "(hidden — run as Administrator)"
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Nearest saved Wi‑Fi",
                    f"SSID: {net.ssid}\n"
                    f"Signal: {net.signal_label}\n"
                    f"BSSID: {net.bssid}\n"
                    f"Auth: {profile.auth}\n\n"
                    f"Password: {pwd}\n\n"
                    f"{profile.notes}".strip(),
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_wifi_double_click(self, _event=None) -> None:
        sel = self.wifi_tree.selection()
        if not sel:
            return
        values = self.wifi_tree.item(sel[0], "values")
        if not values:
            return
        ssid = values[0]
        if ssid == "(hidden)":
            messagebox.showinfo(__app_name__, "Hidden SSIDs cannot be matched to saved profiles by name.")
            return
        profile = password_for_ssid(ssid)
        if profile is None:
            messagebox.showinfo(
                __app_name__,
                f"“{ssid}” is not saved on this PC.\n\n"
                "Only previously joined networks have recoverable passwords.",
            )
            return
        pwd = profile.password or "(hidden — run as Administrator)"
        messagebox.showinfo(
            "Saved profile",
            f"SSID: {profile.name}\nPassword: {pwd}\n{profile.notes}".strip(),
        )

    # --------------------------------------------------------------- creds
    def start_load_profiles(self) -> None:
        if self._busy:
            messagebox.showinfo(__app_name__, "A scan is already running.")
            return
        self._set_busy(True)
        self._set_progress(0)
        self._set_status("Loading saved WLAN profiles…")

        def worker() -> None:
            def on_progress(msg: str, frac: float) -> None:
                self.after(0, lambda: (self._set_status(msg), self._set_progress(frac)))

            try:
                profiles = load_saved_profiles(on_progress=on_progress)
                self.after(0, lambda: self._finish_profiles(profiles))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._fail(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_profiles(self, profiles: list[SavedWifiProfile]) -> None:
        self._profiles = profiles
        self._fill_tree(self.cred_tree, [p.to_row() for p in profiles])
        self._set_busy(False)
        self._set_progress(1)
        self._set_status(f"Loaded {len(profiles)} saved profile(s).")

    def copy_selected_password(self) -> None:
        sel = self.cred_tree.selection()
        if not sel:
            messagebox.showinfo(__app_name__, "Select a profile first.")
            return
        values = self.cred_tree.item(sel[0], "values")
        password = values[3] if len(values) > 3 else ""
        if not password or password.startswith("("):
            messagebox.showinfo(__app_name__, "No copyable password for this row.")
            return
        self.clipboard_clear()
        self.clipboard_append(password)
        self._set_status(f"Copied password for “{values[0]}”.")

    # -------------------------------------------------------------- export
    def _export_csv(self, kind: str) -> None:
        mapping = {
            "devices": (
                self._devices,
                ["ip", "hostname", "mac", "vendor", "latency_ms", "role", "status"],
                lambda d: [
                    d.ip,
                    d.hostname or "",
                    d.mac or "",
                    d.vendor,
                    d.latency_ms if d.latency_ms is not None else "",
                    d.role_label,
                    d.status,
                ],
            ),
            "wifi": (
                self._wifi,
                ["ssid", "bssid", "signal", "channel", "band", "auth", "encryption", "radio"],
                lambda n: [
                    n.ssid,
                    n.bssid,
                    n.signal,
                    n.channel if n.channel is not None else "",
                    n.band,
                    n.auth,
                    n.encryption,
                    n.radio,
                ],
            ),
            "creds": (
                self._profiles,
                ["name", "auth", "encryption", "password", "notes"],
                lambda p: [p.name, p.auth, p.encryption, p.password or "", p.notes],
            ),
        }
        rows_src, headers, mapper = mapping[kind]
        if not rows_src:
            messagebox.showinfo(__app_name__, "Nothing to export yet — run a scan first.")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"netpulse_{kind}_{stamp}.csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        with Path(path).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            for item in rows_src:
                writer.writerow(mapper(item))
        self._set_status(f"Exported {len(rows_src)} row(s) → {path}")

    def _fail(self, message: str) -> None:
        self._set_busy(False)
        self._scanner = None
        self._set_progress(0)
        self._set_status(f"Error: {message}", warn=True)
        messagebox.showerror(__app_name__, message)


def run_app() -> None:
    app = NetPulseApp()
    app.mainloop()
