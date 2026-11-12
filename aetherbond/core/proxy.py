"""
Multi-Interface SOCKS5 & HTTP Forwarding Proxy Server
Transparently aggregates Wi-Fi and Ethernet bandwidth for system applications,
browsers, torrent clients, and game launchers.
"""

from __future__ import annotations

import logging
import select
import socket
import struct
import sys
import threading
from typing import Dict, List, Optional, Tuple

from aetherbond.core.adapter import AdapterManager, NetworkAdapter
from aetherbond.core.socket_factory import BoundSocketFactory
from aetherbond.core.speed_tracker import SpeedTracker

logger = logging.getLogger("aetherbond.proxy")


class MultiNicProxy:
    """Multi-NIC SOCKS5 & HTTP Proxy balancing outbound connections across active adapters."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        socks5_port: int = 1080,
        http_port: int = 8080,
        adapters: Optional[List[NetworkAdapter]] = None,
    ):
        self.host = host
        self.socks5_port = socks5_port
        self.http_port = http_port
        self.requested_adapters = adapters

        self.speed_tracker = SpeedTracker()
        self.stop_event = threading.Event()
        self.adapter_index = 0
        self.lock = threading.Lock()
        self.active_connections = 0

    def _get_next_adapter(self, bondable_adapters: List[NetworkAdapter]) -> NetworkAdapter:
        """Round-robin selection across available hardware adapters."""
        with self.lock:
            if not bondable_adapters:
                raise RuntimeError("No available network adapters for proxy routing.")
            adapter = bondable_adapters[self.adapter_index % len(bondable_adapters)]
            self.adapter_index += 1
            return adapter

    def start(self, blocking: bool = True) -> None:
        mgr = AdapterManager()
        adapters = self.requested_adapters or mgr.get_bondable_adapters(verify_ping=True)
        if not adapters:
            adapters = mgr.get_adapters()

        logger.info(
            "Starting AetherBond Multi-NIC Proxy on SOCKS5 :%d and HTTP :%d with %d bonded adapters: %s",
            self.socks5_port,
            self.http_port,
            len(adapters),
            ", ".join(a.name for a in adapters),
        )

        socks_thread = threading.Thread(target=self._run_socks5_server, args=(adapters,), daemon=True)
        http_thread = threading.Thread(target=self._run_http_server, args=(adapters,), daemon=True)

        socks_thread.start()
        http_thread.start()

        if blocking:
            try:
                while not self.stop_event.is_set():
                    self.stop_event.wait(1.0)
            except KeyboardInterrupt:
                self.stop()

    def stop(self) -> None:
        self.stop_event.set()

    # ----------------- SOCKS5 SERVER -----------------
    def _run_socks5_server(self, adapters: List[NetworkAdapter]) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.socks5_port))
        server.listen(128)
        server.settimeout(1.0)

        logger.info("SOCKS5 Proxy listening on %s:%d", self.host, self.socks5_port)

        while not self.stop_event.is_set():
            try:
                client_sock, client_addr = server.accept()
                t = threading.Thread(
                    target=self._handle_socks5_client,
                    args=(client_sock, client_addr, adapters),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if not self.stop_event.is_set():
                    logger.error("SOCKS5 accept error: %s", e)
                break
        server.close()

    def _handle_socks5_client(
        self,
        client_sock: socket.socket,
        client_addr: Tuple[str, int],
        adapters: List[NetworkAdapter],
    ) -> None:
        try:
            client_sock.settimeout(10.0)
            # SOCKS5 Greeting: [VER, NMETHODS, METHODS...]
            ver_methods = client_sock.recv(2)
            if not ver_methods or len(ver_methods) < 2 or ver_methods[0] != 0x05:
                client_sock.close()
                return

            nmethods = ver_methods[1]
            methods = client_sock.recv(nmethods)

            # Response: [VER, METHOD] (0x00 = NO AUTHENTICATION REQUIRED)
            client_sock.sendall(b"\x05\x00")

            # SOCKS5 Request: [VER, CMD, RSV, ATYP, DST.ADDR, DST.PORT]
            req = client_sock.recv(4)
            if not req or len(req) < 4 or req[0] != 0x05:
                client_sock.close()
                return

            cmd = req[1]
            atyp = req[3]

            if cmd != 0x01:  # Only CONNECT supported
                client_sock.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")  # Command not supported
                client_sock.close()
                return

            # Parse target host
            if atyp == 0x01:  # IPv4
                raw_ip = client_sock.recv(4)
                target_host = socket.inet_ntoa(raw_ip)
            elif atyp == 0x03:  # Domain name
                dlen = client_sock.recv(1)[0]
                target_host = client_sock.recv(dlen).decode("latin-1")
            elif atyp == 0x04:  # IPv6
                raw_ip = client_sock.recv(16)
                target_host = socket.inet_ntop(socket.AF_INET6, raw_ip)
            else:
                client_sock.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                client_sock.close()
                return

            port_bytes = client_sock.recv(2)
            target_port = struct.unpack("!H", port_bytes)[0]

            # Select bonded adapter
            chosen_adapter = self._get_next_adapter(adapters)

            # Connect outbound bound to chosen adapter
            try:
                remote_sock = BoundSocketFactory.connect(
                    adapter=chosen_adapter,
                    host=target_host,
                    port=target_port,
                    timeout=10.0,
                    use_ssl=False,
                )
            except Exception as e:
                logger.debug("Proxy failed to connect via %s to %s:%d: %s", chosen_adapter.name, target_host, target_port, e)
                client_sock.sendall(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")  # Host unreachable
                client_sock.close()
                return

            # Success reply: [VER, REP, RSV, ATYP, BND.ADDR, BND.PORT]
            client_sock.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")

            # Bidirectional pipe
            self._pipe_sockets(client_sock, remote_sock, chosen_adapter)
        except Exception as e:
            logger.debug("SOCKS5 client handler error: %s", e)
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    # ----------------- HTTP CONNECT SERVER -----------------
    def _run_http_server(self, adapters: List[NetworkAdapter]) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.http_port))
        server.listen(128)
        server.settimeout(1.0)

        logger.info("HTTP Proxy listening on %s:%d", self.host, self.http_port)

        while not self.stop_event.is_set():
            try:
                client_sock, client_addr = server.accept()
                t = threading.Thread(
                    target=self._handle_http_client,
                    args=(client_sock, client_addr, adapters),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if not self.stop_event.is_set():
                    logger.error("HTTP accept error: %s", e)
                break
        server.close()

    def _handle_http_client(
        self,
        client_sock: socket.socket,
        client_addr: Tuple[str, int],
        adapters: List[NetworkAdapter],
    ) -> None:
        try:
            client_sock.settimeout(10.0)
            req_data = b""
            while b"\r\n\r\n" not in req_data:
                chunk = client_sock.recv(4096)
                if not chunk:
                    break
                req_data += chunk

            if not req_data:
                client_sock.close()
                return

            header_str = req_data.decode("latin-1", errors="replace")
            first_line = header_str.split("\r\n")[0]
            parts = first_line.split(" ")
            if len(parts) < 2:
                client_sock.close()
                return

            method, target = parts[0], parts[1]

            if method.upper() == "CONNECT":
                # HTTPS Tunneling
                if ":" in target:
                    host, port_str = target.split(":", 1)
                    port = int(port_str)
                else:
                    host = target
                    port = 443

                chosen_adapter = self._get_next_adapter(adapters)
                try:
                    remote_sock = BoundSocketFactory.connect(
                        adapter=chosen_adapter,
                        host=host,
                        port=port,
                        timeout=10.0,
                        use_ssl=False,
                    )
                except Exception as e:
                    client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    client_sock.close()
                    return

                client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._pipe_sockets(client_sock, remote_sock, chosen_adapter)
            else:
                # Plain HTTP proxying
                pass
        except Exception as e:
            logger.debug("HTTP proxy handler error: %s", e)
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    # ----------------- BIDIRECTIONAL PIPE -----------------
    def _pipe_sockets(
        self,
        sock_a: socket.socket,
        sock_b: socket.socket,
        adapter: NetworkAdapter,
        buffer_size: int = 65536,
    ) -> None:
        """Pumps data between client and bound remote socket with speed telemetry."""
        with self.lock:
            self.active_connections += 1

        socks = [sock_a, sock_b]
        sock_a.setblocking(False)
        sock_b.setblocking(False)

        try:
            while not self.stop_event.is_set():
                r, _, _ = select.select(socks, [], socks, 10.0)
                if not r:
                    break

                for s in r:
                    other = sock_b if s is sock_a else sock_a
                    try:
                        data = s.recv(buffer_size)
                    except Exception:
                        data = None

                    if not data:
                        return

                    other.sendall(data)
                    if s is sock_b:
                        # Inbound data from remote server via this adapter
                        self.speed_tracker.record(adapter.name, len(data))
        finally:
            with self.lock:
                self.active_connections = max(0, self.active_connections - 1)
            try:
                sock_a.close()
            except Exception:
                pass
            try:
                sock_b.close()
            except Exception:
                pass
