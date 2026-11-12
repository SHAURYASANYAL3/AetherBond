"""
Formatting Utilities for Speeds, Progress Bars, and Terminal Aesthetics
"""

import sys


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


def render_progress_bar(percent: float, length: int = 24) -> str:
    filled = int(length * (percent / 100.0))
    bar = "█" * filled + "░" * (length - filled)
    return bar
