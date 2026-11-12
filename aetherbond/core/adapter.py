"""
Network Adapter Discovery and Health Management
Handles cross-platform physical/virtual NIC enumeration, interface index resolution,
phone USB tethering (RNDIS/Apple), and hardware-level connectivity validation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("aetherbond.adapter")


@dataclass
class NetworkAdapter:
    name: str
    description: str = ""
    if_index: int = 0
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None
    gateway: Optional[str] = None
    status: str = "Unknown"  # Up, Down, Disconnected
    adapter_type: str = "unknown"  # wifi, ethernet, cellular, virtual, unknown
    link_speed: int = 0  # in bits per second
    is_internet_ready: bool = False
    metric: int = 0

    @property
    def speed_display(self) -> str:
        if self.link_speed >= 1_000_000_000:
            return f"{self.link_speed / 1_000_000_000:.1f} Gbps"
        elif self.link_speed >= 1_000_000:
            return f"{self.link_speed / 1_000_000:.0f} Mbps"
        elif self.link_speed > 0:
            return f"{self.link_speed / 1_000:.0f} Kbps"
        return "Active"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "if_index": self.if_index,
            "ipv4": self.ipv4,
            "ipv6": self.ipv6,
            "gateway": self.gateway,
            "status": self.status,
            "adapter_type": self.adapter_type,
            "link_speed": self.link_speed,
            "speed_display": self.speed_display,
            "is_internet_ready": self.is_internet_ready,
            "metric": self.metric,
        }


def classify_adapter_type(name: str, desc: str) -> str:
    combined = f"{name} {desc}".lower()

    # Explicit Phone USB Tethering & Cellular Devices (DO NOT mark as virtual!)
    if any(k in combined for k in [
        "rndis", "remote ndis", "tether", "cellular", "mobile", "apple mobile",
        "samsung mobile", "android", "lte", "5g", "wwan", "modem"
    ]):
        return "cellular"

    # Known Virtual Host-Only / VPN / Container Adapters
    if any(k in combined for k in [
        "virtualbox host-only", "vmware", "hyper-v", "wsl", "veth", "docker",
        "loopback", "tailscale", "zerotier", "wireguard", "tap-windows"
    ]):
        return "virtual"

    # Wi-Fi / Wireless Adapters
    if any(k in combined for k in ["wi-fi", "wifi", "wlan", "wireless", "802.11"]):
        return "wifi"

    # Standard Ethernet / LAN Adapters
    if any(k in combined for k in ["ethernet", "eth", "realtek", "intel(r) ethernet", "gigabit", "lan"]):
        return "ethernet"

    return "unknown"


class AdapterManager:
    """Discovers and monitors active network adapters across operating systems."""

    def __init__(self):
        self._cached_adapters: List[NetworkAdapter] = []
        self._last_topology_hash: str = ""

    def get_adapters(self, force_refresh: bool = True) -> List[NetworkAdapter]:
        if self._cached_adapters and not force_refresh:
            return self._cached_adapters

        adapters: List[NetworkAdapter] = []
        if sys.platform == "win32":
            adapters = self._discover_windows()
        elif sys.platform.startswith("linux"):
            adapters = self._discover_linux()
        elif sys.platform == "darwin":
            adapters = self._discover_macos()
        else:
            adapters = self._discover_fallback()

        self._cached_adapters = adapters
        return adapters

    def get_bondable_adapters(self, verify_ping: bool = True) -> List[NetworkAdapter]:
        """
        Returns adapters that are suitable for multi-link bonding:
        - Must be Up
        - Must have a valid non-loopback/APIPA IPv4 address
        - Not marked as purely internal virtual host adapter
        - Has a Default Gateway (crucial for internet routing) OR passes reachability probe
        """
        all_adapters = self.get_adapters(force_refresh=True)

        candidates = []
        for a in all_adapters:
            if a.status.lower() != "up":
                continue
            if not a.ipv4 or a.ipv4.startswith("127.") or a.ipv4.startswith("169.254."):
                continue
            if a.adapter_type == "virtual":
                continue
            candidates.append(a)

        if not candidates:
            # Fallback in case cellular or ethernet was tagged as virtual
            for a in all_adapters:
                if a.status.lower() == "up" and a.ipv4 and not a.ipv4.startswith("127.") and not a.ipv4.startswith("169.254."):
                    candidates.append(a)

        verified = []
        for a in candidates:
            # If the adapter has a valid IPv4 Default Gateway, it is a real upstream internet interface!
            if a.gateway and not a.gateway.startswith("0.0.0.0"):
                a.is_internet_ready = True
                verified.append(a)
                continue

            # Otherwise, run reachability probe across multiple endpoints
            if verify_ping:
                if self.test_adapter_reachability(a):
                    a.is_internet_ready = True
                    verified.append(a)
                else:
                    a.is_internet_ready = False
                    logger.warning("Adapter %s (%s) failed internet reachability probe", a.name, a.ipv4)
            else:
                a.is_internet_ready = True
                verified.append(a)

        return verified

    def test_adapter_reachability(self, adapter: NetworkAdapter, timeout: float = 3.5) -> bool:
        """Tests outbound reachability through this specific hardware interface."""
        # Try multiple trusted endpoints: DNS 8.8.8.8:53, Cloudflare 1.1.1.1:443, Google 8.8.4.4:53
        test_targets = [
            ("8.8.8.8", 53),
            ("1.1.1.1", 443),
            ("208.67.222.222", 53),
        ]

        for host, port in test_targets:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(timeout)

                if sys.platform == "win32":
                    IP_UNICAST_IF = 31
                    s.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", adapter.if_index))
                    if adapter.ipv4:
                        try:
                            s.bind((adapter.ipv4, 0))
                        except Exception:
                            pass
                elif sys.platform.startswith("linux"):
                    SO_BINDTODEVICE = 25
                    try:
                        s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, adapter.name.encode() + b"\0")
                    except Exception:
                        if adapter.ipv4:
                            s.bind((adapter.ipv4, 0))
                elif sys.platform == "darwin":
                    IP_BOUND_IF = 25
                    try:
                        s.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, struct.pack("!I", adapter.if_index))
                    except Exception:
                        if adapter.ipv4:
                            s.bind((adapter.ipv4, 0))

                s.connect((host, port))
                s.close()
                return True
            except Exception as e:
                logger.debug("Probe failed on %s to %s:%d: %s", adapter.name, host, port, e)

        return False

    def _discover_windows(self) -> List[NetworkAdapter]:
        adapters: List[NetworkAdapter] = []
        ps_cmd = (
            "$ErrorActionPreference = 'SilentlyContinue'; "
            "$netAdapters = @{}; "
            "Get-NetAdapter | ForEach-Object { "
            "  $netAdapters[$_.ifIndex] = @{ "
            "    Name = $_.Name; "
            "    InterfaceDescription = $_.InterfaceDescription; "
            "    Status = $_.Status; "
            "    LinkSpeed = $_.LinkSpeed; "
            "    InterfaceIndex = $_.ifIndex "
            "  } "
            "}; "
            "$ipConfigs = Get-NetIPConfiguration | ForEach-Object { "
            "  $idx = $_.InterfaceIndex; "
            "  $na = $netAdapters[$idx]; "
            "  $ipv4 = ($_.IPv4Address | Where-Object { $_.IPAddress -notlike '169.254*' -and $_.IPAddress -notlike '127*' } | Select-Object -First 1).IPAddress; "
            "  $ipv6 = ($_.IPv6Address | Select-Object -First 1).IPAddress; "
            "  $gw = ($_.IPv4DefaultGateway | Select-Object -First 1).NextHop; "
            "  [PSCustomObject]@{ "
            "    Name = if ($na) { $na.Name } else { $_.InterfaceAlias }; "
            "    Description = if ($na) { $na.InterfaceDescription } else { '' }; "
            "    Status = if ($na) { $na.Status } else { 'Up' }; "
            "    LinkSpeed = if ($na) { $na.LinkSpeed } else { '' }; "
            "    InterfaceIndex = $idx; "
            "    IPv4 = $ipv4; "
            "    IPv6 = $ipv6; "
            "    Gateway = $gw "
            "  } "
            "}; "
            "$ipConfigs | ConvertTo-Json -Depth 3 -Compress"
        )

        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=8,
            )
            raw = res.stdout.strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    data = [data]

                for item in data:
                    name = str(item.get("Name") or "")
                    desc = str(item.get("Description") or "")
                    idx = int(item.get("InterfaceIndex") or 0)
                    status = str(item.get("Status") or "Unknown")
                    ipv4 = item.get("IPv4")
                    ipv6 = item.get("IPv6")
                    gw = item.get("Gateway")
                    raw_speed = str(item.get("LinkSpeed") or "")
                    speed_bps = self._parse_speed_string(raw_speed)

                    atype = classify_adapter_type(name, desc)

                    adapter = NetworkAdapter(
                        name=name,
                        description=desc,
                        if_index=idx,
                        ipv4=ipv4,
                        ipv6=ipv6,
                        gateway=gw,
                        status=status,
                        adapter_type=atype,
                        link_speed=speed_bps,
                        is_internet_ready=bool(gw and ipv4),
                    )
                    adapters.append(adapter)
        except Exception as e:
            logger.error("Failed to query Windows adapters via PowerShell: %s", e)
            adapters = self._discover_fallback()

        return adapters

    def _parse_speed_string(self, s: str) -> int:
        if not s:
            return 0
        match = re.search(r"([\d\.]+)\s*([GMK]?)bps", s, re.IGNORECASE)
        if not match:
            return 0
        val = float(match.group(1))
        unit = (match.group(2) or "").upper()
        if unit == "G":
            return int(val * 1_000_000_000)
        elif unit == "M":
            return int(val * 1_000_000)
        elif unit == "K":
            return int(val * 1_000)
        return int(val)

    def _discover_linux(self) -> List[NetworkAdapter]:
        adapters: List[NetworkAdapter] = []
        try:
            res = subprocess.run(["ip", "-j", "addr"], capture_output=True, text=True, timeout=5)
            data = json.loads(res.stdout)
            for item in data:
                ifname = item.get("ifname", "")
                ifindex = item.get("ifindex", 0)
                operstate = item.get("operstate", "UNKNOWN").upper()
                status = "Up" if operstate == "UP" else "Down"

                ipv4 = None
                ipv6 = None
                for addr_info in item.get("addr_info", []):
                    fam = addr_info.get("family")
                    local = addr_info.get("local")
                    if fam == "inet" and not ipv4:
                        ipv4 = local
                    elif fam == "inet6" and not ipv6:
                        ipv6 = local

                atype = classify_adapter_type(ifname, "")
                adapter = NetworkAdapter(
                    name=ifname,
                    description=ifname,
                    if_index=ifindex,
                    ipv4=ipv4,
                    ipv6=ipv6,
                    status=status,
                    adapter_type=atype,
                    is_internet_ready=bool(ipv4 and not ipv4.startswith("127.")),
                )
                adapters.append(adapter)
        except Exception as e:
            logger.error("Failed to query Linux ip -j addr: %s", e)
            adapters = self._discover_fallback()

        return adapters

    def _discover_macos(self) -> List[NetworkAdapter]:
        adapters: List[NetworkAdapter] = []
        try:
            if hasattr(socket, "if_nameindex"):
                for idx, name in socket.if_nameindex():
                    atype = classify_adapter_type(name, "")
                    adapter = NetworkAdapter(
                        name=name,
                        description=name,
                        if_index=idx,
                        adapter_type=atype,
                        status="Up",
                        is_internet_ready=True,
                    )
                    adapters.append(adapter)
        except Exception as e:
            logger.error("Failed to query macOS adapters: %s", e)
            adapters = self._discover_fallback()

        return adapters

    def _discover_fallback(self) -> List[NetworkAdapter]:
        adapters = []
        try:
            hostname = socket.gethostname()
            addr_list = socket.getaddrinfo(hostname, None, socket.AF_INET)
            seen_ips = set()
            idx = 1
            for item in addr_list:
                ip = item[4][0]
                if ip not in seen_ips and not ip.startswith("127."):
                    seen_ips.add(ip)
                    adapters.append(
                        NetworkAdapter(
                            name=f"interface_{idx}",
                            description="Network Interface",
                            if_index=idx,
                            ipv4=ip,
                            status="Up",
                            adapter_type="ethernet",
                            is_internet_ready=True,
                        )
                    )
                    idx += 1
        except Exception as e:
            logger.error("Fallback discovery failed: %s", e)
        return adapters
