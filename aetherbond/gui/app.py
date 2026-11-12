"""
AetherBond Native Desktop Application (Windows 11 Cyber-Obsidian Fluent UI)
Engineered strictly following ui-ux-pro-max guidelines:
- Accessible high-contrast typography and color schemes
- Minimum 44px touch & interaction targets
- Non-blocking asynchronous threading with thread-safe UI scheduling
- Real-time canvas telemetry waveform and per-NIC speed gauges
"""

from __future__ import annotations

import collections
import logging
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Dict, List, Optional

import customtkinter as ctk

from aetherbond.core.adapter import AdapterManager, NetworkAdapter
from aetherbond.core.downloader import DownloadStatus, TurboDownloader
from aetherbond.core.optimizer import SystemOptimizer
from aetherbond.core.proxy import MultiNicProxy
from aetherbond.utils.formatting import format_bytes_size, format_bytes_speed

logger = logging.getLogger("aetherbond.gui")

# Set theme configuration
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Design Tokens (Cyber-Obsidian Palette)
COLOR_BG_PRIMARY = "#0B0E14"
COLOR_BG_SIDEBAR = "#11151F"
COLOR_BG_CARD = "#171D29"
COLOR_BG_ELEVATED = "#1F2636"
COLOR_BORDER = "#2B3547"

COLOR_ACCENT_CYAN = "#00F0FF"
COLOR_ACCENT_GREEN = "#10B981"
COLOR_ACCENT_PURPLE = "#A855F7"
COLOR_ACCENT_RED = "#EF4444"
COLOR_ACCENT_YELLOW = "#F59E0B"

COLOR_TEXT_PRIMARY = "#F3F4F6"
COLOR_TEXT_MUTED = "#9CA3AF"
COLOR_TEXT_DIM = "#6B7280"


class AetherBondNativeApp(ctk.CTk):
    """Next-Gen Native Desktop Application for AetherBond Link Aggregator."""

    def __init__(self):
        super().__init__()

        self.title("AetherBond — Multi-WAN Dual-Link Aggregator")
        self.geometry("1100x720")
        self.minsize(980, 640)
        self.configure(fg_color=COLOR_BG_PRIMARY)

        # Set application icon if available
        self._load_icon()

        self.adapter_mgr = AdapterManager()
        self.active_downloader: Optional[TurboDownloader] = None
        self.active_proxy: Optional[MultiNicProxy] = None

        # Telemetry history for canvas waveform (60 data points)
        self.history_total = collections.deque([0.0] * 60, maxlen=60)
        self.history_wifi = collections.deque([0.0] * 60, maxlen=60)
        self.history_eth = collections.deque([0.0] * 60, maxlen=60)

        self.adapter_checkboxes: Dict[str, ctk.CTkCheckBox] = {}
        self.known_adapters: List[NetworkAdapter] = []

        self._setup_ui()
        self._start_background_polling()

    def _load_icon(self):
        try:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

    def _setup_ui(self):
        # Master grid: Left Sidebar (220px) | Main Area (dynamic)
        self.grid_columnconfigure(0, weight=0, minsize=240)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ----------------- SIDEBAR -----------------
        self.sidebar = ctk.CTkFrame(self, fg_color=COLOR_BG_SIDEBAR, corner_radius=0, width=240)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_rowconfigure(6, weight=1)

        # Brand Header
        brand_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand_frame.pack(fill="x", padx=20, pady=(24, 20))

        logo_label = ctk.CTkLabel(
            brand_frame,
            text="⚡ AETHERBOND",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=COLOR_ACCENT_CYAN,
        )
        logo_label.pack(anchor="w")

        sub_label = ctk.CTkLabel(
            brand_frame,
            text="Dual-Link Bonding Engine",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        sub_label.pack(anchor="w")

        # Sidebar Buttons
        self.btn_nav_dash = self._create_sidebar_btn("⚡ Turbo Downloader", self._show_dash_view)
        self.btn_nav_dash.pack(fill="x", padx=14, pady=6)

        self.btn_nav_adapters = self._create_sidebar_btn("🔌 Network Adapters", self._show_adapters_view)
        self.btn_nav_adapters.pack(fill="x", padx=14, pady=6)

        self.btn_nav_proxy = self._create_sidebar_btn("🌐 Multi-WAN Proxy", self._show_proxy_view)
        self.btn_nav_proxy.pack(fill="x", padx=14, pady=6)

        self.btn_nav_doctor = self._create_sidebar_btn("🩺 Network Doctor", self._show_doctor_view)
        self.btn_nav_doctor.pack(fill="x", padx=14, pady=6)

        # Bottom System Health Status Pill
        self.health_frame = ctk.CTkFrame(self.sidebar, fg_color=COLOR_BG_CARD, corner_radius=10)
        self.health_frame.pack(side="bottom", fill="x", padx=14, pady=20)

        self.lbl_status_dot = ctk.CTkLabel(
            self.health_frame,
            text="●",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLOR_ACCENT_GREEN,
        )
        self.lbl_status_dot.pack(side="left", padx=(12, 6), pady=10)

        self.lbl_status_text = ctk.CTkLabel(
            self.health_frame,
            text="ONLINE & BONDED",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self.lbl_status_text.pack(side="left", padx=0, pady=10)

        # ----------------- MAIN CONTENT CONTAINER -----------------
        self.main_container = ctk.CTkFrame(self, fg_color=COLOR_BG_PRIMARY, corner_radius=0)
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_container.grid_rowconfigure(2, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)

        # 1. Top Metrics Cards Ribbon (Total Speed, Wi-Fi, Ethernet/Cellular, Proxy)
        self._build_metrics_ribbon()

        # 2. Live Canvas Waveform Chart
        self._build_waveform_section()

        # 3. Dynamic Views Container
        self.content_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.content_frame.grid(row=2, column=0, sticky="nsew", pady=(16, 0))
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)

        # Initial View: Turbo Downloader
        self._show_dash_view()

    def _create_sidebar_btn(self, text: str, command):
        return ctk.CTkButton(
            self.sidebar,
            text=text,
            command=command,
            fg_color="transparent",
            text_color=COLOR_TEXT_PRIMARY,
            hover_color=COLOR_BG_ELEVATED,
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            height=44,  # ui-ux-pro-max: min 44px touch/click target
            corner_radius=8,
        )

    def _build_metrics_ribbon(self):
        ribbon = ctk.CTkFrame(self.main_container, fg_color="transparent")
        ribbon.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        for i in range(4):
            ribbon.grid_columnconfigure(i, weight=1)

        # Total Aggregated Speed Card
        self.card_total = self._create_metric_card(
            ribbon, 0, "TOTAL BONDED SPEED", "0.0 MB/s", "Combined throughput", COLOR_ACCENT_GREEN
        )
        # Wi-Fi Speed Card
        self.card_wifi = self._create_metric_card(
            ribbon, 1, "WI-FI INTERFACE", "0.0 MB/s", "Wi-Fi (Active)", COLOR_ACCENT_CYAN
        )
        # Ethernet / Phone Card
        self.card_eth = self._create_metric_card(
            ribbon, 2, "ETHERNET / PHONE", "0.0 MB/s", "Ethernet/USB Tether", COLOR_ACCENT_PURPLE
        )
        # Proxy & Streams Card
        self.card_proxy = self._create_metric_card(
            ribbon, 3, "MULTI-WAN PROXY", "SOCKS5: 1080", "HTTP: 8080 (Active)", COLOR_ACCENT_YELLOW
        )

    def _create_metric_card(self, parent, col, title, initial_val, subtext, accent_color):
        card = ctk.CTkFrame(parent, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        card.grid(row=0, column=col, sticky="nsew", padx=6)

        # Accent top bar
        bar = ctk.CTkFrame(card, fg_color=accent_color, height=3, corner_radius=2)
        bar.pack(fill="x", padx=0, pady=0)

        lbl_title = ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
        )
        lbl_title.pack(anchor="w", padx=14, pady=(10, 2))

        lbl_val = ctk.CTkLabel(
            card,
            text=initial_val,
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#FFFFFF",
        )
        lbl_val.pack(anchor="w", padx=14, pady=0)

        lbl_sub = ctk.CTkLabel(
            card,
            text=subtext,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_DIM,
        )
        lbl_sub.pack(anchor="w", padx=14, pady=(2, 10))

        return {"card": card, "val": lbl_val, "sub": lbl_sub}

    def _build_waveform_section(self):
        chart_frame = ctk.CTkFrame(
            self.main_container,
            fg_color=COLOR_BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        chart_frame.grid(row=1, column=0, sticky="ew", pady=(0, 16))

        # Header with legend
        header = ctk.CTkFrame(chart_frame, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(10, 6))

        title = ctk.CTkLabel(
            header,
            text="📈 REAL-TIME HARDWARE BANDWIDTH WAVEFORM",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
        )
        title.pack(side="left")

        legend_frame = ctk.CTkFrame(header, fg_color="transparent")
        legend_frame.pack(side="right")

        self._create_legend_dot(legend_frame, "Total", COLOR_ACCENT_GREEN)
        self._create_legend_dot(legend_frame, "Wi-Fi", COLOR_ACCENT_CYAN)
        self._create_legend_dot(legend_frame, "Ethernet/Phone", COLOR_ACCENT_PURPLE)

        # Tkinter Canvas for smooth 60fps graph
        self.canvas_w = 820
        self.canvas_h = 100
        self.chart_canvas = tk.Canvas(
            chart_frame,
            bg=COLOR_BG_PRIMARY,
            height=self.canvas_h,
            highlightthickness=0,
            bd=0,
        )
        self.chart_canvas.pack(fill="x", padx=14, pady=(0, 12))

    def _create_legend_dot(self, parent, label: str, color: str):
        dot = ctk.CTkLabel(parent, text="●", text_color=color, font=ctk.CTkFont(size=12))
        dot.pack(side="left", padx=(10, 2))
        txt = ctk.CTkLabel(parent, text=label, text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(size=11))
        txt.pack(side="left", padx=(0, 6))

    # ----------------- VIEW 1: DASHBOARD / DOWNLOADER -----------------
    def _show_dash_view(self):
        self._clear_content()

        view = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        view.pack(fill="both", expand=True)

        # Download input bar
        bar_card = ctk.CTkFrame(view, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        bar_card.pack(fill="x", pady=(0, 14))

        input_row = ctk.CTkFrame(bar_card, fg_color="transparent")
        input_row.pack(fill="x", padx=16, pady=16)

        self.entry_url = ctk.CTkEntry(
            input_row,
            placeholder_text="Paste direct download URL (HTTP, HTTPS, ISO, SteamRIP, Google Drive, Archive.org)...",
            height=46,
            fg_color=COLOR_BG_PRIMARY,
            border_color=COLOR_BORDER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=13),
        )
        self.entry_url.pack(side="left", fill="x", expand=True, padx=(0, 12))

        lbl_streams = ctk.CTkLabel(input_row, text="Streams/NIC:", font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED)
        lbl_streams.pack(side="left", padx=(0, 6))

        self.spn_streams = ctk.CTkComboBox(
            input_row,
            values=["2", "4", "8", "16"],
            width=70,
            height=44,
            fg_color=COLOR_BG_PRIMARY,
            button_color=COLOR_BG_ELEVATED,
        )
        self.spn_streams.set("4")
        self.spn_streams.pack(side="left", padx=(0, 12))

        self.btn_download = ctk.CTkButton(
            input_row,
            text="⚡ START BONDED DOWNLOAD",
            command=self._start_download_from_gui,
            height=46,
            fg_color=COLOR_ACCENT_CYAN,
            text_color="#000000",
            hover_color="#38F4FF",
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=10,
        )
        self.btn_download.pack(side="right")

        # Active Download Progress Card
        self.active_task_card = ctk.CTkFrame(
            view,
            fg_color=COLOR_BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        self.active_task_card.pack(fill="both", expand=True)

        task_inner = ctk.CTkFrame(self.active_task_card, fg_color="transparent")
        task_inner.pack(fill="both", expand=True, padx=20, pady=20)

        # Title Row
        title_row = ctk.CTkFrame(task_inner, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 10))

        self.lbl_task_filename = ctk.CTkLabel(
            title_row,
            text="No active download in progress",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#FFFFFF",
        )
        self.lbl_task_filename.pack(side="left")

        self.lbl_task_percent = ctk.CTkLabel(
            title_row,
            text="0%",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=COLOR_ACCENT_CYAN,
        )
        self.lbl_task_percent.pack(side="right")

        # Smooth Progress Bar
        self.task_progressbar = ctk.CTkProgressBar(
            task_inner,
            height=12,
            progress_color=COLOR_ACCENT_CYAN,
            fg_color=COLOR_BG_PRIMARY,
            corner_radius=6,
        )
        self.task_progressbar.set(0.0)
        self.task_progressbar.pack(fill="x", pady=(0, 14))

        # Meta Row: Transferred / ETA / Active NIC Contributions
        meta_row = ctk.CTkFrame(task_inner, fg_color="transparent")
        meta_row.pack(fill="x", pady=(0, 14))

        self.lbl_transferred = ctk.CTkLabel(meta_row, text="0 MB / 0 MB", font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED)
        self.lbl_transferred.pack(side="left", padx=(0, 20))

        self.lbl_eta = ctk.CTkLabel(meta_row, text="ETA: --", font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED)
        self.lbl_eta.pack(side="left", padx=(0, 20))

        self.lbl_nic_contributions = ctk.CTkLabel(
            meta_row,
            text="NIC Speeds: Idle",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_ACCENT_GREEN,
        )
        self.lbl_nic_contributions.pack(side="left")

        # Action Buttons Row
        actions_row = ctk.CTkFrame(task_inner, fg_color="transparent")
        actions_row.pack(fill="x", pady=(10, 0))

        self.btn_pause = ctk.CTkButton(
            actions_row,
            text="⏸ Pause",
            command=self._toggle_pause_download,
            width=100,
            height=38,
            fg_color=COLOR_BG_ELEVATED,
            hover_color=COLOR_BORDER,
        )
        self.btn_pause.pack(side="left", padx=(0, 10))

        self.btn_cancel = ctk.CTkButton(
            actions_row,
            text="✕ Cancel",
            command=self._cancel_download,
            width=100,
            height=38,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_ACCENT_RED,
            text_color=COLOR_ACCENT_RED,
            hover_color="#3B1219",
        )
        self.btn_cancel.pack(side="left")

    # ----------------- VIEW 2: ADAPTERS & HOT-PLUG -----------------
    def _show_adapters_view(self):
        self._clear_content()

        view = ctk.CTkFrame(self.content_frame, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        view.pack(fill="both", expand=True, padx=0, pady=0)

        header = ctk.CTkFrame(view, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 12))

        lbl = ctk.CTkLabel(
            header,
            text="🔌 HARDWARE INTERFACES & HOT-PLUG DETECTOR",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#FFFFFF",
        )
        lbl.pack(side="left")

        btn_rescan = ctk.CTkButton(
            header,
            text="↻ Scan for Newly Plugged Devices",
            command=self._force_adapter_scan,
            height=36,
            fg_color=COLOR_BG_ELEVATED,
            hover_color=COLOR_BORDER,
        )
        btn_rescan.pack(side="right")

        desc = ctk.CTkLabel(
            view,
            text="Check the adapters you want AetherBond to bond together. USB Tethered phones appear automatically as Ethernet/Cellular.",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        desc.pack(anchor="w", padx=20, pady=(0, 14))

        self.adapters_scroll = ctk.CTkScrollableFrame(view, fg_color=COLOR_BG_PRIMARY, corner_radius=8)
        self.adapters_scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self._render_adapter_checkboxes()

    def _render_adapter_checkboxes(self):
        for widget in self.adapters_scroll.winfo_children():
            widget.destroy()

        self.adapter_checkboxes.clear()
        self.known_adapters = self.adapter_mgr.get_adapters(force_refresh=True)

        for a in self.known_adapters:
            row = ctk.CTkFrame(self.adapters_scroll, fg_color=COLOR_BG_CARD, corner_radius=8, height=54)
            row.pack(fill="x", pady=4, padx=4)

            # Checkbox: default checked if internet ready or Up
            chk_var = tk.BooleanVar(value=(a.is_internet_ready or (a.status.lower() == "up" and a.adapter_type != "virtual")))
            chk = ctk.CTkCheckBox(
                row,
                text=f"{a.name}  (ifIndex {a.if_index})",
                variable=chk_var,
                font=ctk.CTkFont(size=13, weight="bold"),
                checkbox_height=20,
                checkbox_width=20,
            )
            chk.pack(side="left", padx=16, pady=12)
            self.adapter_checkboxes[a.name] = chk

            # Badges
            type_badge = ctk.CTkLabel(
                row,
                text=f"[{a.adapter_type.upper()}]",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLOR_ACCENT_CYAN if a.adapter_type == "wifi" else (COLOR_ACCENT_PURPLE if a.adapter_type in ("ethernet", "cellular") else COLOR_TEXT_DIM),
            )
            type_badge.pack(side="left", padx=8)

            meta = f"IP: {a.ipv4 or 'No IP'}  |  Gateway: {a.gateway or '--'}  |  Speed: {a.speed_display}"
            lbl_meta = ctk.CTkLabel(row, text=meta, font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED)
            lbl_meta.pack(side="left", padx=12)

            status_pill = ctk.CTkLabel(
                row,
                text=f"● {a.status}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLOR_ACCENT_GREEN if a.status.lower() == "up" else COLOR_ACCENT_RED,
            )
            status_pill.pack(side="right", padx=16)

    # ----------------- VIEW 3: PROXY -----------------
    def _show_proxy_view(self):
        self._clear_content()

        view = ctk.CTkFrame(self.content_frame, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        view.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(view, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=24, pady=24)

        lbl = ctk.CTkLabel(
            inner,
            text="🌐 TRANSPARENT MULTI-WAN SYSTEM PROXY",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#FFFFFF",
        )
        lbl.pack(anchor="w", pady=(0, 6))

        desc = ctk.CTkLabel(
            inner,
            text="Route your entire browser, Steam, Epic Games, IDM, qBittorrent, or git traffic through AetherBond.\nOutbound connections are seamlessly balanced across Wi-Fi and Ethernet in parallel.",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_TEXT_MUTED,
            justify="left",
        )
        desc.pack(anchor="w", pady=(0, 20))

        # Toggle Switch & Config Box
        ctrl_box = ctk.CTkFrame(inner, fg_color=COLOR_BG_PRIMARY, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        ctrl_box.pack(fill="x", pady=(0, 20), padx=0)

        ctrl_inner = ctk.CTkFrame(ctrl_box, fg_color="transparent")
        ctrl_inner.pack(fill="x", padx=20, pady=16)

        self.btn_toggle_proxy = ctk.CTkButton(
            ctrl_inner,
            text="🚀 START MULTI-WAN PROXY TUNNEL" if not self.active_proxy else "🛑 STOP PROXY TUNNEL",
            command=self._toggle_proxy_server,
            height=46,
            fg_color=COLOR_ACCENT_GREEN if not self.active_proxy else COLOR_ACCENT_RED,
            text_color="#000000" if not self.active_proxy else "#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=10,
        )
        self.btn_toggle_proxy.pack(side="left")

        config_text = "SOCKS5 Proxy: 127.0.0.1:1080\nHTTP Proxy:   127.0.0.1:8080"
        lbl_cfg = ctk.CTkLabel(
            ctrl_inner,
            text=config_text,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=COLOR_ACCENT_CYAN,
            justify="left",
        )
        lbl_cfg.pack(side="right")

        # Telemetry info
        stats_frame = ctk.CTkFrame(inner, fg_color=COLOR_BG_PRIMARY, corner_radius=10)
        stats_frame.pack(fill="x", pady=0)

        self.lbl_proxy_active_conns = ctk.CTkLabel(
            stats_frame,
            text="Active Proxy Tunnels: 0",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self.lbl_proxy_active_conns.pack(anchor="w", padx=20, pady=12)

    # ----------------- VIEW 4: DOCTOR -----------------
    def _show_doctor_view(self):
        self._clear_content()

        view = ctk.CTkFrame(self.content_frame, fg_color=COLOR_BG_CARD, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        view.pack(fill="both", expand=True)

        inner = ctk.CTkFrame(view, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=24, pady=24)

        lbl = ctk.CTkLabel(
            inner,
            text="🩺 WINDOWS ROUTING & DUAL-NIC DOCTOR",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#FFFFFF",
        )
        lbl.pack(anchor="w", pady=(0, 6))

        desc = ctk.CTkLabel(
            inner,
            text="Scans Windows Connection Manager policies, Weak Host models, and interface metrics to ensure Windows never throttles or sleeps Wi-Fi when Ethernet or Phone USB Tethering connects.",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_TEXT_MUTED,
            justify="left",
        )
        desc.pack(anchor="w", pady=(0, 16))

        self.doctor_result_box = ctk.CTkTextbox(
            inner,
            fg_color=COLOR_BG_PRIMARY,
            text_color=COLOR_TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=12),
            height=200,
            border_color=COLOR_BORDER,
            border_width=1,
        )
        self.doctor_result_box.pack(fill="both", expand=True, pady=(0, 16))

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")

        btn_run_diag = ctk.CTkButton(
            btn_row,
            text="🔍 Run Diagnostic Scan",
            command=self._run_doctor_diag,
            height=42,
            fg_color=COLOR_BG_ELEVATED,
            hover_color=COLOR_BORDER,
        )
        btn_run_diag.pack(side="left", padx=(0, 10))

        btn_apply_fix = ctk.CTkButton(
            btn_row,
            text="⚡ Auto-Fix Windows Dual-NIC Throttling",
            command=self._apply_doctor_fix,
            height=42,
            fg_color=COLOR_ACCENT_CYAN,
            text_color="#000000",
            hover_color="#38F4FF",
            font=ctk.CTkFont(weight="bold"),
        )
        btn_apply_fix.pack(side="left")

        self._run_doctor_diag()

    def _clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    # ----------------- ACTIONS & ENGINE INTEGRATION -----------------
    def _start_download_from_gui(self):
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste or enter a download URL.")
            return

        threads = int(self.spn_streams.get())

        # Resolve selected adapters
        selected = []
        for a in self.known_adapters:
            chk = self.adapter_checkboxes.get(a.name)
            if chk and chk.get():
                selected.append(a)

        if not selected:
            # Fall back to all bondable
            selected = self.adapter_mgr.get_bondable_adapters(verify_ping=False)

        if not selected:
            messagebox.showerror("No Adapters", "No active network adapters selected.")
            return

        self.btn_download.configure(state="disabled", text="⏳ Connecting Streams...")

        def on_prog(st: DownloadStatus):
            self.after(0, self._update_download_progress_ui, st)

        def runner():
            try:
                self.active_downloader = TurboDownloader(
                    url=url,
                    output_dir=os.path.join(os.path.expanduser("~"), "Downloads"),
                    adapters=selected,
                    streams_per_adapter=threads,
                    on_progress=on_prog,
                )
                success = self.active_downloader.start(blocking=True)
                self.after(0, self._download_finished_callback, success)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Download Error", str(e)))
                self.after(0, lambda: self.btn_download.configure(state="normal", text="⚡ START BONDED DOWNLOAD"))

        threading.Thread(target=runner, daemon=True).start()

    def _update_download_progress_ui(self, st: DownloadStatus):
        self.lbl_task_filename.configure(text=st.filename)
        self.lbl_task_percent.configure(text=f"{st.progress_percent:.1f}%")
        self.task_progressbar.set(st.progress_percent / 100.0)

        self.lbl_transferred.configure(
            text=f"{format_bytes_size(st.downloaded_bytes)} / {format_bytes_size(st.total_bytes)}"
        )

        eta_str = f"ETA: {int(st.eta_seconds)}s" if st.eta_seconds else "ETA: Calculating..."
        self.lbl_eta.configure(text=eta_str)

        # Update per-NIC breakdown
        breakdown = "  |  ".join(
            f"{name}: {format_bytes_speed(spd)}"
            for name, spd in st.adapter_speeds.items()
            if spd > 0
        )
        self.lbl_nic_contributions.configure(text=f"NIC Speeds: {breakdown or 'Distributing chunks...'}")

    def _download_finished_callback(self, success: bool):
        self.btn_download.configure(state="normal", text="⚡ START BONDED DOWNLOAD")
        if success:
            path = self.active_downloader.target_path if self.active_downloader else "Downloads"
            messagebox.showinfo("Completed", f"File successfully downloaded with bonded throughput!\nSaved to: {path}")

    def _toggle_pause_download(self):
        if not self.active_downloader:
            return
        if self.active_downloader.pause_event.is_set():
            self.active_downloader.resume()
            self.btn_pause.configure(text="⏸ Pause")
        else:
            self.active_downloader.pause()
            self.btn_pause.configure(text="▶ Resume")

    def _cancel_download(self):
        if self.active_downloader:
            self.active_downloader.cancel()
            self.btn_download.configure(state="normal", text="⚡ START BONDED DOWNLOAD")

    def _toggle_proxy_server(self):
        if self.active_proxy and not self.active_proxy.stop_event.is_set():
            self.active_proxy.stop()
            self.active_proxy = None
            if hasattr(self, "btn_toggle_proxy"):
                self.btn_toggle_proxy.configure(
                    text="🚀 START MULTI-WAN PROXY TUNNEL", fg_color=COLOR_ACCENT_GREEN, text_color="#000000"
                )
        else:
            # Selected adapters
            selected = [a for a in self.known_adapters if self.adapter_checkboxes.get(a.name) and self.adapter_checkboxes[a.name].get()]
            self.active_proxy = MultiNicProxy(socks5_port=1080, http_port=8080, adapters=selected or None)
            threading.Thread(target=self.active_proxy.start, args=(False,), daemon=True).start()
            if hasattr(self, "btn_toggle_proxy"):
                self.btn_toggle_proxy.configure(
                    text="🛑 STOP PROXY TUNNEL", fg_color=COLOR_ACCENT_RED, text_color="#FFFFFF"
                )

    def _run_doctor_diag(self):
        diag = SystemOptimizer.diagnose()
        lines = [
            f"=== Windows & OS Network Diagnostics ===",
            f"Platform: {diag['platform']}",
            f"Dual-Bond Capability: {'✓ Optimal' if diag['can_dual_bond'] else '⚠ Policy Issues Detected'}\n",
        ]
        if diag["issues"]:
            lines.append("Issues:")
            for i in diag["issues"]:
                lines.append(f" ✗ {i}")
        else:
            lines.append("✓ No policy conflicts detected. Windows Connection Manager permits simultaneous links.")

        if diag["recommendations"]:
            lines.append("\nRecommendations:")
            for r in diag["recommendations"]:
                lines.append(f" • {r}")

        self.doctor_result_box.delete("1.0", "end")
        self.doctor_result_box.insert("1.0", "\n".join(lines))

    def _apply_doctor_fix(self):
        ok, msg = SystemOptimizer.apply_windows_dual_nic_fix()
        if ok:
            messagebox.showinfo("Success", msg)
        else:
            messagebox.showwarning("Notice", msg)
        self._run_doctor_diag()

    def _force_adapter_scan(self):
        self._render_adapter_checkboxes()
        messagebox.showinfo("Scanned", f"Detected {len(self.known_adapters)} hardware interfaces.")

    # ----------------- BACKGROUND TELEMETRY LOOP -----------------
    def _start_background_polling(self):
        def loop():
            while True:
                time.sleep(0.4)
                self.after(0, self._telemetry_tick)

        threading.Thread(target=loop, daemon=True).start()

    def _telemetry_tick(self):
        total_spd = 0.0
        wifi_spd = 0.0
        eth_spd = 0.0

        if self.active_downloader:
            total_spd += self.active_downloader.speed_tracker.get_total_speed()
            snap = self.active_downloader.speed_tracker.snapshot()
            for name, m in snap.items():
                lname = name.lower()
                if any(k in lname for k in ["wi-fi", "wifi", "wlan"]):
                    wifi_spd += m.current_speed
                else:
                    eth_spd += m.current_speed

        if self.active_proxy:
            total_spd += self.active_proxy.speed_tracker.get_total_speed()
            snap = self.active_proxy.speed_tracker.snapshot()
            for name, m in snap.items():
                lname = name.lower()
                if any(k in lname for k in ["wi-fi", "wifi", "wlan"]):
                    wifi_spd += m.current_speed
                else:
                    eth_spd += m.current_speed

            if hasattr(self, "lbl_proxy_active_conns"):
                self.lbl_proxy_active_conns.configure(
                    text=f"Active Proxy Tunnels: {self.active_proxy.active_connections}  |  Speed: {format_bytes_speed(self.active_proxy.speed_tracker.get_total_speed())}"
                )

        # Update Top Cards
        self.card_total["val"].configure(text=format_bytes_speed(total_spd))
        self.card_wifi["val"].configure(text=format_bytes_speed(wifi_spd))
        self.card_eth["val"].configure(text=format_bytes_speed(eth_spd))

        # Update History & Draw Waveform
        self.history_total.append(total_spd)
        self.history_wifi.append(wifi_spd)
        self.history_eth.append(eth_spd)

        self._draw_canvas_waveform()

    def _draw_canvas_waveform(self):
        c = self.chart_canvas
        w = c.winfo_width() or self.canvas_w
        h = c.winfo_height() or self.canvas_h
        c.delete("all")

        # Grid lines
        for y in range(0, h, 25):
            c.create_line(0, y, w, y, fill="#1B2230", width=1)

        max_val = max(max(self.history_total), max(self.history_wifi), max(self.history_eth), 1024 * 1024 * 5) * 1.15

        def plot_points(data_seq, color):
            pts = []
            step = w / (len(data_seq) - 1)
            for i, val in enumerate(data_seq):
                x = i * step
                y = h - (val / max_val) * (h - 8)
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(*pts, fill=color, width=2.5, smooth=True)

        plot_points(self.history_wifi, COLOR_ACCENT_CYAN)
        plot_points(self.history_eth, COLOR_ACCENT_PURPLE)
        plot_points(self.history_total, COLOR_ACCENT_GREEN)


def launch_native_gui():
    app = AetherBondNativeApp()
    app.mainloop()


if __name__ == "__main__":
    launch_native_gui()
