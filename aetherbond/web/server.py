"""
Lightweight Web Dashboard and Telemetry API Server
Pure standard-library HTTP & Server-Sent Events (SSE) server for zero-dependency real-time UI.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from aetherbond.core.adapter import AdapterManager
from aetherbond.core.downloader import DownloadStatus, TurboDownloader
from aetherbond.core.optimizer import SystemOptimizer
from aetherbond.core.proxy import MultiNicProxy

logger = logging.getLogger("aetherbond.web")

# Shared state between Web Server and Background Engines
_active_downloader: Optional[TurboDownloader] = None
_active_proxy: Optional[MultiNicProxy] = None
_latest_status: Optional[dict] = None
_status_lock = threading.Lock()


def set_active_downloader(dl: Optional[TurboDownloader]) -> None:
    global _active_downloader
    _active_downloader = dl


def set_active_proxy(pr: Optional[MultiNicProxy]) -> None:
    global _active_proxy
    _active_proxy = pr


class AetherWebHandler(BaseHTTPRequestHandler):
    """Handles REST API requests and serves static dashboard assets."""

    def log_message(self, format, *args):
        # Silence standard HTTP access logs to keep console clean
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/adapters":
            self._handle_get_adapters()
        elif path == "/api/status":
            self._handle_get_status()
        elif path == "/api/doctor":
            self._handle_get_doctor()
        elif path == "/events":
            self._handle_sse_stream()
        else:
            self._serve_static_file(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}

        if path == "/api/download":
            self._handle_post_download(payload)
        elif path == "/api/pause":
            if _active_downloader:
                _active_downloader.pause()
            self._send_json({"status": "paused"})
        elif path == "/api/resume":
            if _active_downloader:
                _active_downloader.resume()
            self._send_json({"status": "resumed"})
        elif path == "/api/cancel":
            if _active_downloader:
                _active_downloader.cancel()
            self._send_json({"status": "cancelled"})
        elif path == "/api/proxy/start":
            self._handle_start_proxy(payload)
        elif path == "/api/proxy/stop":
            if _active_proxy:
                _active_proxy.stop()
            self._send_json({"status": "proxy_stopped"})
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def _handle_get_adapters(self):
        mgr = AdapterManager()
        adapters = mgr.get_adapters(force_refresh=True)
        data = [a.to_dict() for a in adapters]
        self._send_json(data)

    def _handle_get_status(self):
        global _latest_status
        data = self._build_status_payload()
        self._send_json(data)

    def _handle_get_doctor(self):
        report = SystemOptimizer.diagnose()
        self._send_json(report)

    def _handle_post_download(self, payload: dict):
        url = payload.get("url", "").strip()
        threads = int(payload.get("threads", 4))
        if not url:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing URL")
            return

        def on_prog(st: DownloadStatus):
            global _latest_status
            with _status_lock:
                _latest_status = {
                    "filename": st.filename,
                    "target_path": st.target_path,
                    "total_bytes": st.total_bytes,
                    "downloaded_bytes": st.downloaded_bytes,
                    "progress_percent": st.progress_percent,
                    "total_speed_bps": st.total_speed_bps,
                    "eta_seconds": st.eta_seconds,
                    "is_completed": st.is_completed,
                    "is_paused": st.is_paused,
                    "is_failed": st.is_failed,
                    "active_adapters": st.active_adapters,
                    "adapter_speeds": st.adapter_speeds,
                    "sha256": st.sha256_hash,
                }

        dl = TurboDownloader(
            url=url,
            output_dir="./downloads",
            streams_per_adapter=threads,
            on_progress=on_prog,
        )
        set_active_downloader(dl)
        dl.start(blocking=False)

        self._send_json({"status": "download_started", "url": url})

    def _handle_start_proxy(self, payload: dict):
        global _active_proxy
        if _active_proxy and not _active_proxy.stop_event.is_set():
            self._send_json({"status": "proxy_already_running"})
            return

        socks_port = int(payload.get("socks_port", 1080))
        http_port = int(payload.get("http_port", 8080))

        pr = MultiNicProxy(socks5_port=socks_port, http_port=http_port)
        set_active_proxy(pr)
        threading.Thread(target=pr.start, args=(False,), daemon=True).start()

        self._send_json({
            "status": "proxy_started",
            "socks5_port": socks_port,
            "http_port": http_port,
        })

    def _handle_sse_stream(self):
        """Streams real-time speed & chunk events to the browser using Server-Sent Events."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            while True:
                payload = self._build_status_payload()
                msg = f"data: {json.dumps(payload)}\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.3)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _build_status_payload(self) -> dict:
        mgr = AdapterManager()
        adapters = [a.to_dict() for a in mgr.get_adapters()]

        download_info = None
        if _active_downloader:
            if _active_downloader.chunk_engine:
                cstats = _active_downloader.chunk_engine.get_progress_stats()
                snap = _active_downloader.speed_tracker.snapshot()
                total_spd = _active_downloader.speed_tracker.get_total_speed()
                eta = _active_downloader.speed_tracker.get_eta_seconds(cstats["total_bytes"] - cstats["downloaded_bytes"])

                download_info = {
                    "filename": _active_downloader.probe_info.filename if _active_downloader.probe_info else "file",
                    "total_bytes": cstats["total_bytes"],
                    "downloaded_bytes": cstats["downloaded_bytes"],
                    "progress_percent": cstats["percent"],
                    "total_speed_bps": total_spd,
                    "eta_seconds": eta,
                    "is_completed": _active_downloader.is_completed,
                    "is_paused": _active_downloader.pause_event.is_set(),
                    "is_failed": _active_downloader.is_failed,
                    "adapter_speeds": {k: v.current_speed for k, v in snap.items()},
                    "sha256": _active_downloader.sha256_checksum,
                }

        proxy_info = None
        if _active_proxy:
            proxy_snap = _active_proxy.speed_tracker.snapshot()
            proxy_info = {
                "is_running": not _active_proxy.stop_event.is_set(),
                "socks5_port": _active_proxy.socks5_port,
                "http_port": _active_proxy.http_port,
                "active_connections": _active_proxy.active_connections,
                "total_speed_bps": _active_proxy.speed_tracker.get_total_speed(),
                "adapter_speeds": {k: v.current_speed for k, v in proxy_snap.items()},
            }

        return {
            "timestamp": time.time(),
            "adapters": adapters,
            "download": download_info,
            "proxy": proxy_info,
        }

    def _serve_static_file(self, req_path: str):
        if req_path in ("/", ""):
            req_path = "/index.html"

        static_dir = os.path.join(os.path.dirname(__file__), "static")
        full_path = os.path.normpath(os.path.join(static_dir, req_path.lstrip("/")))

        if not full_path.startswith(static_dir) or not os.path.isfile(full_path):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        mime_type, _ = mimetypes.guess_type(full_path)
        mime_type = mime_type or "application/octet-stream"

        try:
            with open(full_path, "rb") as f:
                content = f.read()

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error reading file: {e}")

    def _send_json(self, data: any, status_code: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def run_web_dashboard(host: str = "127.0.0.1", port: int = 8765, blocking: bool = True) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), AetherWebHandler)
    logger.info("AetherBond Web UI available at http://%s:%d", host, port)
    if blocking:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
    return server
