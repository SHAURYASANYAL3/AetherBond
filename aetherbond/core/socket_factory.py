"""
Hardware-Bound Socket Factory
Guarantees physical NIC route steering using Winsock IP_UNICAST_IF on Windows,
SO_BINDTODEVICE on Linux, and IP_BOUND_IF on macOS.
"""

from __future__ import annotations

import logging
import socket
import ssl
import struct
import sys
from typing import Optional, Tuple
from aetherbond.core.adapter import NetworkAdapter

logger = logging.getLogger("aetherbond.socket")

# Constant definitions for platform socket options
IP_UNICAST_IF = 31      # Windows Winsock ws2ipdef.h
IPV6_UNICAST_IF = 31    # Windows Winsock ws2ipdef.h
SO_BINDTODEVICE = 25    # Linux asm/socket.h
IP_BOUND_IF = 25        # macOS sys/socket.h
IPV6_BOUND_IF = 125     # macOS


class BoundSocketFactory:
    """Creates outbound sockets strictly bound to a designated physical network interface."""

    @staticmethod
    def create_socket(
        adapter: NetworkAdapter,
        family: int = socket.AF_INET,
        sock_type: int = socket.SOCK_STREAM,
        timeout: float = 10.0,
        buffer_size: int = 1048576,  # 1MB socket buffer for high throughput
    ) -> socket.socket:
        sock = socket.socket(family, sock_type)
        sock.settimeout(timeout)

        # Optimize TCP options for high-throughput streaming
        if sock_type == socket.SOCK_STREAM:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass

        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_size)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_size)
        except Exception:
            pass

        # Apply platform-specific hardware interface binding
        BoundSocketFactory.apply_interface_binding(sock, adapter, is_ipv6=(family == socket.AF_INET6))
        return sock

    @staticmethod
    def apply_interface_binding(sock: socket.socket, adapter: NetworkAdapter, is_ipv6: bool = False) -> None:
        """
        Binds the socket directly to the hardware adapter's interface index
        and optionally binds to its local IP address.
        """
        if sys.platform == "win32":
            # On Windows, IP_UNICAST_IF forces outbound frames to the specified IF index
            # bypassing default gateway metric bias (solving Plexo #65).
            idx_bytes = struct.pack("!I", adapter.if_index)
            try:
                if is_ipv6:
                    sock.setsockopt(socket.IPPROTO_IPV6, IPV6_UNICAST_IF, idx_bytes)
                else:
                    sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, idx_bytes)
            except Exception as e:
                logger.debug("Failed setting IP_UNICAST_IF on adapter %s: %s", adapter.name, e)

            # Bind to adapter IP if available
            bind_ip = adapter.ipv6 if is_ipv6 else adapter.ipv4
            if bind_ip:
                try:
                    sock.bind((bind_ip, 0))
                except Exception as e:
                    logger.debug("Warning: could not bind source IP %s: %s", bind_ip, e)

        elif sys.platform.startswith("linux"):
            # Linux SO_BINDTODEVICE
            try:
                if_bytes = adapter.name.encode() + b"\0"
                sock.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, if_bytes)
            except PermissionError:
                # Requires CAP_NET_RAW; fall back to local IP binding
                bind_ip = adapter.ipv6 if is_ipv6 else adapter.ipv4
                if bind_ip:
                    sock.bind((bind_ip, 0))
            except Exception as e:
                logger.debug("SO_BINDTODEVICE failed: %s", e)

        elif sys.platform == "darwin":
            # macOS IP_BOUND_IF
            try:
                idx_bytes = struct.pack("!I", adapter.if_index)
                if is_ipv6:
                    sock.setsockopt(socket.IPPROTO_IPV6, IPV6_BOUND_IF, idx_bytes)
                else:
                    sock.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, idx_bytes)
            except Exception:
                bind_ip = adapter.ipv6 if is_ipv6 else adapter.ipv4
                if bind_ip:
                    sock.bind((bind_ip, 0))
        else:
            bind_ip = adapter.ipv6 if is_ipv6 else adapter.ipv4
            if bind_ip:
                sock.bind((bind_ip, 0))

    @staticmethod
    def connect(
        adapter: NetworkAdapter,
        host: str,
        port: int,
        timeout: float = 10.0,
        use_ssl: bool = False,
        server_hostname: Optional[str] = None,
        buffer_size: int = 1048576,
    ) -> socket.socket | ssl.SSLSocket:
        """
        Resolves host, creates a bound socket on the specified adapter,
        connects to target host:port, and optionally completes TLS handshake.
        """
        # Resolve address
        addr_info = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        if not addr_info:
            raise ConnectionError(f"Could not resolve host: {host}")

        family, socktype, proto, canonname, sockaddr = addr_info[0]

        sock = BoundSocketFactory.create_socket(
            adapter=adapter,
            family=family,
            sock_type=socktype,
            timeout=timeout,
            buffer_size=buffer_size,
        )

        try:
            sock.connect(sockaddr)
        except Exception as e:
            sock.close()
            raise ConnectionError(f"Connection failed via adapter {adapter.name} ({adapter.ipv4}) to {host}:{port}: {e}")

        if use_ssl:
            context = ssl.create_default_context()
            hostname = server_hostname or host
            try:
                ssl_sock = context.wrap_socket(sock, server_hostname=hostname)
                return ssl_sock
            except Exception as e:
                sock.close()
                raise ConnectionError(f"TLS handshake failed via adapter {adapter.name} to {hostname}: {e}")

        return sock
