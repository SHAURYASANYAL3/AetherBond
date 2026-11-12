"""
Parallel Multi-NIC Turbo Downloader
Coordinates distributed thread workers across bonded hardware adapters,
handles pre-allocation, zero-lock parallel file writing, and zero-downtime failover.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from aetherbond.core.adapter import AdapterManager, NetworkAdapter
from aetherbond.core.chunk_engine import Chunk, ChunkEngine
from aetherbond.core.http_client import BoundHttpClient, ProbeResult
from aetherbond.core.speed_tracker import SpeedTracker

logger = logging.getLogger("aetherbond.downloader")


@dataclass
class DownloadStatus:
    filename: str
    target_path: str
    total_bytes: int
    downloaded_bytes: int
    progress_percent: float
    total_speed_bps: float
    eta_seconds: Optional[float]
    is_completed: bool
    is_paused: bool
    is_failed: bool
    active_adapters: List[str]
    adapter_speeds: Dict[str, float]
    sha256_hash: Optional[str] = None


class TurboDownloader:
    """Multi-threaded, multi-interface download orchestrator."""

    def __init__(
        self,
        url: str,
        output_dir: str = ".",
        filename: Optional[str] = None,
        adapters: Optional[List[NetworkAdapter]] = None,
        streams_per_adapter: int = 4,
        on_progress: Optional[Callable[[DownloadStatus], None]] = None,
    ):
        self.url = url
        self.output_dir = os.path.abspath(output_dir)
        self.custom_filename = filename
        self.requested_adapters = adapters
        self.streams_per_adapter = streams_per_adapter
        self.on_progress = on_progress

        self.speed_tracker = SpeedTracker()
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.file_lock = threading.Lock()

        self.probe_info: Optional[ProbeResult] = None
        self.chunk_engine: Optional[ChunkEngine] = None
        self.target_path: str = ""
        self.state_file_path: str = ""
        self.active_adapters: List[NetworkAdapter] = []
        self.is_completed = False
        self.is_failed = False
        self.sha256_checksum: Optional[str] = None

    def start(self, blocking: bool = True) -> bool:
        """Starts the accelerated multi-interface download."""
        os.makedirs(self.output_dir, exist_ok=True)

        # 1. Probe URL to determine size and range capability
        logger.info("Probing target: %s", self.url)
        self.probe_info = BoundHttpClient.probe_url(self.url)
        fname = self.custom_filename or self.probe_info.filename
        self.target_path = os.path.join(self.output_dir, fname)
        self.state_file_path = f"{self.target_path}.aetherpart"

        # 2. Resolve active internet-ready adapters
        if self.requested_adapters:
            self.active_adapters = self.requested_adapters
        else:
            mgr = AdapterManager()
            self.active_adapters = mgr.get_bondable_adapters(verify_ping=True)
            if not self.active_adapters:
                logger.warning("No verified multi-NIC adapters found; falling back to all active adapters")
                self.active_adapters = mgr.get_adapters()

        if not self.active_adapters:
            raise RuntimeError("No usable network adapters detected on this system.")

        logger.info(
            "Bonding %d adapters for download: %s",
            len(self.active_adapters),
            ", ".join(f"{a.name} ({a.ipv4})" for a in self.active_adapters),
        )

        # 3. Initialize or restore chunk engine
        total_size = self.probe_info.content_length
        if self.probe_info.supports_ranges and total_size > 0:
            if os.path.exists(self.state_file_path) and os.path.exists(self.target_path):
                self.chunk_engine = ChunkEngine.load_state(self.state_file_path)
                logger.info("Resuming previous partial download from state file.")

            if not self.chunk_engine:
                self.chunk_engine = ChunkEngine(total_size=total_size)
                self._preallocate_target_file(self.target_path, total_size)
                self.chunk_engine.save_state(self.state_file_path)
        else:
            # Server does not support ranges: download with single stream
            logger.info("Server does not support HTTP ranges; downloading as single stream.")
            return self._download_single_stream()

        # 4. Launch multi-threaded workers across each adapter
        if blocking:
            return self._run_parallel_download()
        else:
            t = threading.Thread(target=self._run_parallel_download, daemon=True)
            t.start()
            return True

    def _preallocate_target_file(self, path: str, size: int) -> None:
        """Pre-allocates the file on disk to allow concurrent write seeking."""
        logger.info("Pre-allocating %s (%d bytes)", path, size)
        with open(path, "wb") as f:
            if size > 0:
                f.seek(size - 1)
                f.write(b"\0")

    def _run_parallel_download(self) -> bool:
        threads = []
        total_workers = len(self.active_adapters) * self.streams_per_adapter

        # Telemetry reporter thread
        reporter_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        reporter_thread.start()

        # Launch worker pool
        with ThreadPoolExecutor(max_workers=total_workers) as executor:
            futures = []
            for adapter in self.active_adapters:
                for stream_idx in range(self.streams_per_adapter):
                    f = executor.submit(self._adapter_worker, adapter, stream_idx)
                    futures.append(f)

            # Wait for all workers to finish
            for f in futures:
                try:
                    f.result()
                except Exception as e:
                    logger.error("Worker error: %s", e)

        # Check completion
        if self.chunk_engine and self.chunk_engine.is_all_completed():
            self.is_completed = True
            logger.info("Download completed successfully! Verifying integrity...")

            # Clean up state file
            if os.path.exists(self.state_file_path):
                try:
                    os.remove(self.state_file_path)
                except Exception:
                    pass

            self.sha256_checksum = self._calculate_checksum(self.target_path)
            logger.info("SHA-256: %s", self.sha256_checksum)
            return True
        else:
            if not self.stop_event.is_set():
                self.is_failed = True
            return False

    def _adapter_worker(self, adapter: NetworkAdapter, stream_idx: int) -> None:
        """Worker thread dedicated to an adapter that claims and downloads chunks."""
        file_handle = open(self.target_path, "r+b", buffering=0)

        try:
            while not self.stop_event.is_set():
                while self.pause_event.is_set():
                    time.sleep(0.2)
                    if self.stop_event.is_set():
                        return

                chunk = self.chunk_engine.get_next_chunk(adapter.name)
                if not chunk:
                    # No more chunks for this worker to grab
                    break

                success = self._download_chunk(adapter, chunk, file_handle)
                if success:
                    self.chunk_engine.mark_completed(chunk.id)
                    # Periodic save of state every few chunks
                    if chunk.id % 4 == 0:
                        self.chunk_engine.save_state(self.state_file_path)
                else:
                    self.chunk_engine.mark_failed(chunk.id)
                    # Brief backoff if adapter is experiencing network flap
                    time.sleep(0.5)
        finally:
            file_handle.close()

    def _download_chunk(self, adapter: NetworkAdapter, chunk: Chunk, file_handle) -> bool:
        """Streams a single chunk over the designated adapter and writes to disk."""
        start_offset = chunk.start + chunk.downloaded
        end_offset = chunk.end

        if start_offset > end_offset:
            return True

        def write_callback(data: bytes, current_offset: int) -> None:
            # Thread-safe write to pre-allocated file
            with self.file_lock:
                file_handle.seek(current_offset)
                file_handle.write(data)

            self.chunk_engine.update_progress(chunk.id, len(data))
            self.speed_tracker.record(adapter.name, len(data))

        try:
            bytes_streamed = BoundHttpClient.stream_range(
                adapter=adapter,
                url=self.probe_info.final_url,
                start_byte=start_offset,
                end_byte=end_offset,
                on_data_chunk=write_callback,
                stop_event=self.stop_event,
            )
            return bytes_streamed >= (end_offset - start_offset + 1)
        except Exception as e:
            logger.debug("Chunk %d failed on adapter %s: %s", chunk.id, adapter.name, e)
            return False

    def _download_single_stream(self) -> bool:
        """Fallback for servers that don't support HTTP Range header."""
        adapter = self.active_adapters[0]
        logger.info("Streaming sequentially via %s", adapter.name)

        parsed_url = self.probe_info.final_url
        with open(self.target_path, "wb") as f:
            def write_cb(data: bytes, offset: int):
                f.write(data)
                self.speed_tracker.record(adapter.name, len(data))

            BoundHttpClient.stream_range(
                adapter=adapter,
                url=parsed_url,
                start_byte=0,
                end_byte=self.probe_info.content_length - 1 if self.probe_info.content_length > 0 else 10**9,
                on_data_chunk=write_cb,
                stop_event=self.stop_event,
            )

        self.is_completed = True
        return True

    def _telemetry_loop(self) -> None:
        """Emits real-time progress events to callbacks."""
        while not self.stop_event.is_set() and not self.is_completed:
            time.sleep(0.25)
            if self.on_progress and self.chunk_engine:
                stats = self.chunk_engine.get_progress_stats()
                total_spd = self.speed_tracker.get_total_speed()
                eta = self.speed_tracker.get_eta_seconds(stats["total_bytes"] - stats["downloaded_bytes"])
                snap = self.speed_tracker.snapshot()

                adapter_speeds = {k: v.current_speed for k, v in snap.items()}

                status = DownloadStatus(
                    filename=self.probe_info.filename if self.probe_info else "file",
                    target_path=self.target_path,
                    total_bytes=stats["total_bytes"],
                    downloaded_bytes=stats["downloaded_bytes"],
                    progress_percent=stats["percent"],
                    total_speed_bps=total_spd,
                    eta_seconds=eta,
                    is_completed=self.is_completed,
                    is_paused=self.pause_event.is_set(),
                    is_failed=self.is_failed,
                    active_adapters=[a.name for a in self.active_adapters],
                    adapter_speeds=adapter_speeds,
                )
                self.on_progress(status)

    def pause(self) -> None:
        self.pause_event.set()
        if self.chunk_engine:
            self.chunk_engine.save_state(self.state_file_path)

    def resume(self) -> None:
        self.pause_event.clear()

    def cancel(self) -> None:
        self.stop_event.set()

    def _calculate_checksum(self, filepath: str) -> str:
        sha = hashlib.sha256()
        with open(filepath, "rb") as f:
            for block in iter(lambda: f.read(1048576), b""):
                sha.update(block)
        return sha.hexdigest()
