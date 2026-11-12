"""
Network Adapter Discovery and Health Management
Handles cross-platform physical/virtual NIC enumeration, interface index resolution,
and hardware-level connectivity validation.
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
        return "N/A"

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
    if any(k in combined for k in ["virtualbox", "vmware", "hyper-v", "wsl", "veth", "docker", "loopback", "tap", "vpn", "tailscale", "zerotier"]):
        return "virtual"
    if any(k in combined for k in ["wi-fi", "wifi", "wlan", "wireless", "802.11"]):
        return "wifi"
    if any(k in combined for k in ["ethernet", "eth", "realtek", "intel(r) ethernet", "gigabit", "lan"]):
        return "ethernet"
    if any(k in combined for k in ["cellular", "mobile", "lte", "5g", "wwan", "modem"]):
        return "cellular"
    return "unknown"


class AdapterManager:
    """Discovers and monitors active network adapters across operating systems."""

    def __init__(self):
        self._cached_adapters: List[NetworkAdapter] = []

    def get_adapters(self, force_refresh: bool = False) -> List[NetworkAdapter]:
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
        - Not marked as purely internal virtual host adapter (unless requested)
        - Must pass socket reachability probe if verify_ping is True
        """
        all_adapters = self.get_adapters(force_refresh=True)
        candidates = [
            a for a in all_adapters
            if a.status.lower() == "up"
            and a.ipv4
            and not a.ipv4.startswith("127.")
            and not a.ipv4.startswith("169.254.")
            and a.adapter_type != "virtual"
        ]

        if not candidates:
            # Fallback: maybe the user is using a USB tethered connection that classified as virtual or unknown
            candidates = [
                a for a in all_adapters
                if a.status.lower() == "up" and a.ipv4 and not a.ipv4.startswith("127.") and not a.ipv4.startswith("169.254.")
            ]

        if not verify_ping:
            return candidates

        verified = []
        for a in candidates:
            if self.test_adapter_reachability(a):
                a.is_internet_ready = True
                verified.append(a)
            else:
                a.is_internet_ready = False
                logger.warning("Adapter %s (%s) failed internet reachability probe", a.name, a.ipv4)

        return verified

    def test_adapter_reachability(self, adapter: NetworkAdapter, host: str = "1.1.1.1", port: int = 80, timeout: float = 2.5) -> bool:
        """Tests whether an outbound connection can actually be made through this specific interface."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)

            # Apply interface-specific routing
            if sys.platform == "win32":
                IP_UNICAST_IF = 31
                s.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", adapter.if_index))
                if adapter.ipv4:
                    s.bind((adapter.ipv4, 0))
            elif sys.platform.startswith("linux"):
                SO_BINDTODEVICE = 25
                try:
                    s.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, adapter.name.encode() + b"\0")
                except PermissionError:
                    if adapter.ipv4:
                        s.bind((adapter.ipv4, 0))
            elif sys.platform == "darwin":
                IP_BOUND_IF = 25
                try:
                    s.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, struct.pack("!I", adapter.if_index))
                except Exception:
                    if adapter.ipv4:
                        s.bind((adapter.ipv4, 0))
            else:
                if adapter.ipv4:
                    s.bind((adapter.ipv4, 0))

            s.connect((host, port))
            s.close()
            return True
        except Exception as e:
            logger.debug("Reachability check failed for adapter %s: %s", adapter.name, e)
            return False

    def _discover_windows(self) -> List[NetworkAdapter]:
        adapters: List[NetworkAdapter] = []
        # Query PowerShell for structured network adapter and IP configuration
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
            "  $ipv4 = ($_.IPv4Address | Select-Object -First 1).IPAddress; "
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
                timeout=10,
            )
            raw = res.stdout.strip()
            if raw:
                # Can be a single object or an array
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

                    # Parse speed string like "433.3 Mbps" or "1 Gbps"
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
                )
                adapters.append(adapter)
        except Exception as e:
            logger.error("Failed to query Linux ip -j addr: %s", e)
            adapters = self._discover_fallback()

        return adapters

    def _discover_macos(self) -> List[NetworkAdapter]:
        adapters: List[NetworkAdapter] = []
        try:
            res = subprocess.run(["networksetup", "-listallhardwareports"], capture_output=True, text=True, timeout=5)
            # Parse Hardware Port, Device
            lines = res.stdout.splitlines()
            current_port = ""
            current_dev = ""
            device_map = {}
            for line in lines:
                if line.startswith("Hardware Port:"):
                    current_port = line.split(":", 1)[1].strip()
                elif line.startswith("Device:"):
                    current_dev = line.split(":", 1)[1].strip()
                    if current_port and current_dev:
                        device_map[current_dev] = current_port
                        current_port = ""
                        current_dev = ""

            # Use socket.if_nameindex to find indexes
            if hasattr(socket, "if_nameindex"):
                for idx, name in socket.if_nameindex():
                    port_name = device_map.get(name, name)
                    atype = classify_adapter_type(port_name, name)
                    adapter = NetworkAdapter(
                        name=name,
                        description=port_name,
                        if_index=idx,
                        adapter_type=atype,
                        status="Up",
                    )
                    adapters.append(adapter)
        except Exception as e:
            logger.error("Failed to query macOS adapters: %s", e)
            adapters = self._discover_fallback()

        return adapters

    def _discover_fallback(self) -> List[NetworkAdapter]:
        """Portable fallback using standard library socket methods."""
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
                            name=f"nic_{idx}",
                            description="Network Interface",
                            if_index=idx,
                            ipv4=ip,
                            status="Up",
                            adapter_type="ethernet",
                        )
                    )
                    idx += 1
        except Exception as e:
            logger.error("Fallback discovery failed: %s", e)
        return adapters
