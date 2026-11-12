"""
Real-Time Speed and Bandwidth Telemetry Tracker
Tracks per-adapter and aggregate throughput with sliding window EWMA smoothing.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional


@dataclass
class AdapterMetrics:
    adapter_name: str
    total_bytes: int = 0
    current_speed: float = 0.0  # bytes per second
    peak_speed: float = 0.0
    active_streams: int = 0
    latency_ms: float = 0.0

    @property
    def speed_display(self) -> str:
        return format_bytes_speed(self.current_speed)

    @property
    def total_display(self) -> str:
        return format_bytes_size(self.total_bytes)


def format_bytes_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec >= 1024 * 1024 * 1024:
        return f"{bytes_per_sec / (1024**3):.2f} GB/s"
    elif bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024**2):.2f} MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    return f"{bytes_per_sec:.0f} B/s"


def format_bytes_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024 * 1024:
        return f"{num_bytes / (1024**3):.2f} GB"
    elif num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024**2):.2f} MB"
    elif num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


class SpeedMeter:
    """Sliding-window speed meter for an individual adapter or overall stream."""

    def __init__(self, window_seconds: float = 1.5):
        self.window_seconds = window_seconds
        self.history: deque[tuple[float, int]] = deque()
        self.total_bytes: int = 0
        self.peak_speed: float = 0.0
        self.lock = Lock()
        self._last_speed: float = 0.0

    def add_bytes(self, byte_count: int) -> None:
        now = time.time()
        with self.lock:
            self.total_bytes += byte_count
            self.history.append((now, byte_count))
            self._prune(now)

    def _prune(self, now: float) -> None:
        threshold = now - self.window_seconds
        while self.history and self.history[0][0] < threshold:
            self.history.popleft()

    def get_current_speed(self) -> float:
        now = time.time()
        with self.lock:
            self._prune(now)
            if len(self.history) < 2:
                # If only 1 point or none, check time since last record
                if self.history:
                    delta = now - self.history[0][0]
                    if delta > 0:
                        return self.history[0][1] / max(delta, 0.1)
                return 0.0

            dt = now - self.history[0][0]
            if dt <= 0.05:
                return self._last_speed

            total_window_bytes = sum(b for _, b in self.history)
            speed = total_window_bytes / dt
            self._last_speed = speed
            if speed > self.peak_speed:
                self.peak_speed = speed
            return speed


class SpeedTracker:
    """Multi-NIC aggregated speed tracker coordinating per-adapter telemetry."""

    def __init__(self):
        self.meters: Dict[str, SpeedMeter] = {}
        self.active_streams: Dict[str, int] = {}
        self.latencies: Dict[str, float] = {}
        self.total_meter = SpeedMeter(window_seconds=1.5)
        self.lock = Lock()
        self.start_time = time.time()

    def record(self, adapter_name: str, byte_count: int) -> None:
        with self.lock:
            if adapter_name not in self.meters:
                self.meters[adapter_name] = SpeedMeter()
                self.active_streams[adapter_name] = 0
            meter = self.meters[adapter_name]

        meter.add_bytes(byte_count)
        self.total_meter.add_bytes(byte_count)

    def set_streams(self, adapter_name: str, count: int) -> None:
        with self.lock:
            self.active_streams[adapter_name] = count

    def set_latency(self, adapter_name: str, latency_ms: float) -> None:
        with self.lock:
            self.latencies[adapter_name] = latency_ms

    def snapshot(self) -> Dict[str, AdapterMetrics]:
        with self.lock:
            adapters = list(self.meters.keys())

        res = {}
        for name in adapters:
            meter = self.meters[name]
            res[name] = AdapterMetrics(
                adapter_name=name,
                total_bytes=meter.total_bytes,
                current_speed=meter.get_current_speed(),
                peak_speed=meter.peak_speed,
                active_streams=self.active_streams.get(name, 0),
                latency_ms=self.latencies.get(name, 0.0),
            )
        return res

    def get_total_speed(self) -> float:
        return self.total_meter.get_current_speed()

    def get_total_bytes(self) -> int:
        return self.total_meter.total_bytes

    def get_eta_seconds(self, remaining_bytes: int) -> Optional[float]:
        spd = self.get_total_speed()
        if spd > 1024 and remaining_bytes > 0:
            return remaining_bytes / spd
        return None
