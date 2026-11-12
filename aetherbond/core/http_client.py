"""
Multi-Interface HTTP/HTTPS Range Streaming Client
Performs zero-copy socket range requests bound to hardware network adapters.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import ssl
import sys
import threading
import time
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from aetherbond.core.adapter import NetworkAdapter
from aetherbond.core.socket_factory import BoundSocketFactory

logger = logging.getLogger("aetherbond.http")


class ProbeResult:
    def __init__(
        self,
        final_url: str,
        content_length: int,
        supports_ranges: bool,
        filename: str,
        etag: Optional[str] = None,
    ):
        self.final_url = final_url
        self.content_length = content_length
        self.supports_ranges = supports_ranges
        self.filename = filename
        self.etag = etag

    def to_dict(self) -> dict:
        return {
            "final_url": self.final_url,
            "content_length": self.content_length,
            "supports_ranges": self.supports_ranges,
            "filename": self.filename,
            "etag": self.etag,
        }


def extract_filename_from_url(url: str, content_disposition: Optional[str] = None) -> str:
    if content_disposition:
        match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)["\']?', content_disposition, re.IGNORECASE)
        if match:
            return unquote(match.group(1).strip())

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path:
        base = os.path.basename(path)
        if base:
            return unquote(base)
    return "downloaded_file"


class BoundHttpClient:
    """HTTP client performing range requests over hardware-bound sockets."""

    @staticmethod
    def probe_url(url: str, adapter: Optional[NetworkAdapter] = None, timeout: float = 10.0) -> ProbeResult:
        """
        Follows redirects and inspects Content-Length and Range support via HEAD or GET range probe.
        """
        current_url = url
        redirects_left = 8
        final_headers: Dict[str, str] = {}
        status_code = 0

        while redirects_left > 0:
            parsed = urlparse(current_url)
            host = parsed.hostname
            if not host:
                raise ValueError(f"Invalid URL: {current_url}")

            use_ssl = parsed.scheme.lower() == "https"
            port = parsed.port or (443 if use_ssl else 80)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"

            # If an adapter was given, bind to it; otherwise standard socket
            if adapter:
                sock = BoundSocketFactory.connect(adapter, host, port, timeout=timeout, use_ssl=use_ssl)
            else:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(timeout)
                s.connect((host, port))
                if use_ssl:
                    ctx = ssl.create_default_context()
                    sock = ctx.wrap_socket(s, server_hostname=host)
                else:
                    sock = s

            try:
                # Use HEAD first; if server rejects HEAD with 405/403, fall back to GET Range 0-0
                req = (
                    f"HEAD {path} HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    f"User-Agent: AetherBond/2.0 (Multi-NIC Accelerator)\r\n"
                    f"Accept: */*\r\n"
                    f"Connection: close\r\n\r\n"
                )
                sock.sendall(req.encode())

                raw_resp = b""
                while b"\r\n\r\n" not in raw_resp:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    raw_resp += chunk

                header_bytes, _, _ = raw_resp.partition(b"\r\n\r\n")
                status_code, headers = BoundHttpClient._parse_headers(header_bytes)

                # Fallback to GET 0-0 if HEAD not permitted
                if status_code in (403, 405, 501):
                    sock.close()
                    if adapter:
                        sock = BoundSocketFactory.connect(adapter, host, port, timeout=timeout, use_ssl=use_ssl)
                    else:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(timeout)
                        s.connect((host, port))
                        sock = ssl.create_default_context().wrap_socket(s, server_hostname=host) if use_ssl else s

                    get_req = (
                        f"GET {path} HTTP/1.1\r\n"
                        f"Host: {host}\r\n"
                        f"User-Agent: AetherBond/2.0 (Multi-NIC Accelerator)\r\n"
                        f"Range: bytes=0-0\r\n"
                        f"Connection: close\r\n\r\n"
                    )
                    sock.sendall(get_req.encode())
                    raw_resp = b""
                    while b"\r\n\r\n" not in raw_resp:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        raw_resp += chunk
                    header_bytes, _, _ = raw_resp.partition(b"\r\n\r\n")
                    status_code, headers = BoundHttpClient._parse_headers(header_bytes)

            finally:
                sock.close()

            # Handle redirects
            if status_code in (301, 302, 303, 307, 308):
                loc = headers.get("location")
                if not loc:
                    break
                if loc.startswith("http"):
                    current_url = loc
                else:
                    current_url = f"{parsed.scheme}://{parsed.netloc}{loc}"
                redirects_left -= 1
                continue

            final_headers = headers
            break

        # Analyze Content-Length and Range headers
        content_length = -1
        if "content-length" in final_headers:
            try:
                content_length = int(final_headers["content-length"])
            except ValueError:
                pass

        # Check content-range if returned (e.g. bytes 0-0/123456)
        if "content-range" in final_headers:
            match = re.search(r"bytes\s+\d+-\d+/(\d+|\*)", final_headers["content-range"], re.IGNORECASE)
            if match and match.group(1) != "*":
                content_length = int(match.group(1))

        supports_ranges = (
            final_headers.get("accept-ranges", "").lower() == "bytes"
            or "content-range" in final_headers
            or status_code == 206
        )

        filename = extract_filename_from_url(current_url, final_headers.get("content-disposition"))
        etag = final_headers.get("etag")

        return ProbeResult(
            final_url=current_url,
            content_length=content_length,
            supports_ranges=supports_ranges,
            filename=filename,
            etag=etag,
        )

    @staticmethod
    def _parse_headers(header_bytes: bytes) -> Tuple[int, Dict[str, str]]:
        text = header_bytes.decode("iso-8859-1", errors="replace")
        lines = text.split("\r\n")
        if not lines:
            return 0, {}

        status_line = lines[0]
        status_parts = status_line.split(" ", 2)
        status_code = int(status_parts[1]) if len(status_parts) > 1 and status_parts[1].isdigit() else 0

        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        return status_code, headers

    @staticmethod
    def stream_range(
        adapter: NetworkAdapter,
        url: str,
        start_byte: int,
        end_byte: int,
        on_data_chunk: Callable[[bytes, int], None],
        stop_event: threading.Event,
        buffer_size: int = 65536,
        timeout: float = 12.0,
    ) -> int:
        """
        Connects via designated adapter, streams [start_byte, end_byte],
        invoking on_data_chunk(bytes, current_offset) for each payload buffer.
        Returns total bytes written.
        """
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            raise ValueError(f"Invalid host in {url}")

        use_ssl = parsed.scheme.lower() == "https"
        port = parsed.port or (443 if use_ssl else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        sock = BoundSocketFactory.connect(adapter, host, port, timeout=timeout, use_ssl=use_ssl)

        try:
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"User-Agent: AetherBond/2.0 (Multi-NIC Turbo Downloader)\r\n"
                f"Range: bytes={start_byte}-{end_byte}\r\n"
                f"Accept: */*\r\n"
                f"Connection: close\r\n\r\n"
            )
            sock.sendall(req.encode())

            # Read headers
            raw_buf = b""
            while b"\r\n\r\n" not in raw_buf:
                if stop_event.is_set():
                    return 0
                chunk = sock.recv(4096)
                if not chunk:
                    break
                raw_buf += chunk

            header_bytes, _, leftover_body = raw_buf.partition(b"\r\n\r\n")
            status_code, headers = BoundHttpClient._parse_headers(header_bytes)

            if status_code not in (200, 206):
                raise IOError(f"Unexpected HTTP status {status_code} during range request {start_byte}-{end_byte}")

            total_received = 0
            expected_bytes = end_byte - start_byte + 1

            # Process leftover body in header buffer
            if leftover_body:
                take_len = min(len(leftover_body), expected_bytes - total_received)
                chunk_slice = leftover_body[:take_len]
                on_data_chunk(chunk_slice, start_byte + total_received)
                total_received += len(chunk_slice)

            # Stream remainder
            while total_received < expected_bytes:
                if stop_event.is_set():
                    break
                to_read = min(buffer_size, expected_bytes - total_received)
                data = sock.recv(to_read)
                if not data:
                    break
                on_data_chunk(data, start_byte + total_received)
                total_received += len(data)

            return total_received
        finally:
            sock.close()
