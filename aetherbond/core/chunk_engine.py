"""
Dynamic Multi-NIC Chunk Distribution and Tail Racing Engine
Schedules byte-ranges across heterogeneous network links with dynamic work-stealing
and latency-adaptive tail-end chunk racing.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger("aetherbond.chunk")

CHUNK_STATUS_PENDING = "pending"
CHUNK_STATUS_DOWNLOADING = "downloading"
CHUNK_STATUS_COMPLETED = "completed"
CHUNK_STATUS_FAILED = "failed"


@dataclass
class Chunk:
    id: int
    start: int
    end: int
    downloaded: int = 0
    status: str = CHUNK_STATUS_PENDING
    assigned_adapter: Optional[str] = None
    assigned_time: float = 0.0
    completed_time: float = 0.0
    retries: int = 0

    @property
    def total_bytes(self) -> int:
        return self.end - self.start + 1

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.total_bytes - self.downloaded)

    @property
    def is_finished(self) -> bool:
        return self.status == CHUNK_STATUS_COMPLETED or (self.downloaded >= self.total_bytes)


class ChunkEngine:
    """Manages chunk partitioning, dynamic allocation, and speculative racing."""

    def __init__(self, total_size: int, chunk_size: Optional[int] = None):
        self.total_size = total_size
        self.chunk_size = chunk_size or self._calculate_optimal_chunk_size(total_size)
        self.chunks: List[Chunk] = []
        self.lock = Lock()
        self._init_chunks()

    def _calculate_optimal_chunk_size(self, total_bytes: int) -> int:
        # Scale chunk size dynamically to balance multi-NIC parallelism and HTTP overhead
        if total_bytes < 5 * 1024 * 1024:          # < 5 MB: 512 KB chunks
            return 512 * 1024
        elif total_bytes < 50 * 1024 * 1024:       # < 50 MB: 2 MB chunks
            return 2 * 1024 * 1024
        elif total_bytes < 500 * 1024 * 1024:      # < 500 MB: 8 MB chunks
            return 8 * 1024 * 1024
        elif total_bytes < 5 * 1024 * 1024 * 1024: # < 5 GB: 16 MB chunks
            return 16 * 1024 * 1024
        else:                                      # >= 5 GB: 32 MB chunks
            return 32 * 1024 * 1024

    def _init_chunks(self) -> None:
        if self.total_size <= 0:
            return

        chunk_id = 0
        current = 0
        while current < self.total_size:
            end = min(current + self.chunk_size - 1, self.total_size - 1)
            self.chunks.append(
                Chunk(
                    id=chunk_id,
                    start=current,
                    end=end,
                    downloaded=0,
                    status=CHUNK_STATUS_PENDING,
                )
            )
            chunk_id += 1
            current = end + 1

    def get_next_chunk(self, adapter_name: str) -> Optional[Chunk]:
        """Atomically grabs the next pending chunk for the requesting adapter."""
        with self.lock:
            for chunk in self.chunks:
                if chunk.status == CHUNK_STATUS_PENDING:
                    chunk.status = CHUNK_STATUS_DOWNLOADING
                    chunk.assigned_adapter = adapter_name
                    chunk.assigned_time = time.time()
                    return chunk

            # If no pending chunks remain, check if we should race a lagging chunk
            return self._find_raceable_chunk(adapter_name)

    def _find_raceable_chunk(self, racing_adapter_name: str) -> Optional[Chunk]:
        """
        Tail-End Racing: If all chunks are assigned and only a few are downloading,
        idle fast connections can race the slowest lagging chunk to eliminate tail latency.
        """
        now = time.time()
        slowest_chunk: Optional[Chunk] = None
        max_duration = 0.0

        for chunk in self.chunks:
            if chunk.status == CHUNK_STATUS_DOWNLOADING and chunk.assigned_adapter != racing_adapter_name:
                duration = now - chunk.assigned_time
                # Only race if it has been running for at least 3 seconds and has remaining bytes
                if duration > 3.0 and chunk.remaining_bytes > 256 * 1024:
                    if duration > max_duration:
                        max_duration = duration
                        slowest_chunk = chunk

        return slowest_chunk

    def mark_completed(self, chunk_id: int) -> None:
        with self.lock:
            if 0 <= chunk_id < len(self.chunks):
                chunk = self.chunks[chunk_id]
                chunk.status = CHUNK_STATUS_COMPLETED
                chunk.downloaded = chunk.total_bytes
                chunk.completed_time = time.time()

    def mark_failed(self, chunk_id: int) -> None:
        with self.lock:
            if 0 <= chunk_id < len(self.chunks):
                chunk = self.chunks[chunk_id]
                chunk.retries += 1
                if chunk.retries > 5:
                    chunk.status = CHUNK_STATUS_FAILED
                else:
                    chunk.status = CHUNK_STATUS_PENDING
                    chunk.assigned_adapter = None

    def update_progress(self, chunk_id: int, bytes_written: int) -> None:
        with self.lock:
            if 0 <= chunk_id < len(self.chunks):
                chunk = self.chunks[chunk_id]
                chunk.downloaded = min(chunk.total_bytes, chunk.downloaded + bytes_written)
                if chunk.downloaded >= chunk.total_bytes:
                    chunk.status = CHUNK_STATUS_COMPLETED

    def is_all_completed(self) -> bool:
        with self.lock:
            return all(c.status == CHUNK_STATUS_COMPLETED for c in self.chunks)

    def get_progress_stats(self) -> dict:
        with self.lock:
            total_chunks = len(self.chunks)
            completed_chunks = sum(1 for c in self.chunks if c.status == CHUNK_STATUS_COMPLETED)
            active_chunks = sum(1 for c in self.chunks if c.status == CHUNK_STATUS_DOWNLOADING)
            downloaded_bytes = sum(c.downloaded for c in self.chunks)

            percent = (downloaded_bytes / self.total_size * 100.0) if self.total_size > 0 else 0.0

            return {
                "total_chunks": total_chunks,
                "completed_chunks": completed_chunks,
                "active_chunks": active_chunks,
                "downloaded_bytes": downloaded_bytes,
                "total_bytes": self.total_size,
                "percent": percent,
                "is_complete": completed_chunks == total_chunks,
            }

    def save_state(self, filepath: str) -> None:
        with self.lock:
            data = {
                "total_size": self.total_size,
                "chunk_size": self.chunk_size,
                "chunks": [asdict(c) for c in self.chunks],
            }
        temp_path = f"{filepath}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(temp_path, filepath)

    @classmethod
    def load_state(cls, filepath: str) -> Optional["ChunkEngine"]:
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            engine = cls(total_size=data["total_size"], chunk_size=data["chunk_size"])
            engine.chunks = []
            for item in data["chunks"]:
                # Reset downloading to pending on load
                if item["status"] == CHUNK_STATUS_DOWNLOADING:
                    item["status"] = CHUNK_STATUS_PENDING
                engine.chunks.append(Chunk(**item))
            return engine
        except Exception as e:
            logger.error("Failed to restore chunk engine state from %s: %s", filepath, e)
            return None
