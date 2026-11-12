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
from dataclasses import dataclass
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

    # Explicit Virtual Host-Only / Sandbox Adapters (STRICT FILTER: NEVER BOND THESE!)
    if any(k in combined for k in [
        "virtualbox", "vmware", "hyper-v", "wsl", "veth", "docker",
        "loopback", "tailscale", "zerotier", "wireguard", "tap-windows"
    ]):
        return "virtual"

    # Phone USB Tethering & Cellular Devices (Remote NDIS, Apple Mobile, Samsung, LTE, 5G)
    cellular_keywords = [
        "rndis", "remote ndis", "tether", "cellular", "apple mobile",
        "samsung mobile", "android", "wwan", "modem"
    ]
    if any(k in combined for k in cellular_keywords) or re.search(r"\b(lte|5g|4g|mobile)\b", combined):
        return "cellular"

    # Wi-Fi / Wireless Adapters
    if any(k in combined for k in ["wi-fi", "wifi", "wlan", "wireless", "802.11"]):
        return "wifi"

    # Standard Physical Ethernet Adapters
    if any(k in combined for k in ["ethernet", "eth", "realtek", "intel(r) ethernet", "gigabit", "lan"]):
        return "ethernet"

    return "unknown"


class AdapterManager:
    """Discovers and monitors active network adapters across operating systems."""

    def __init__(self):
        self._cached_adapters: List[NetworkAdapter] = []

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

    def get_bondable_adapters(self, verify_ping: bool = False) -> List[NetworkAdapter]:
        """
        Returns adapters strictly suitable for internet link bonding:
        - Must be Up
        - Must have a valid non-loopback/APIPA IPv4 address
        - Must NOT be a virtual host-only adapter (e.g. VirtualBox)
        - MUST have a valid IPv4 Default Gateway (proof of upstream internet routing)
        """
        all_adapters = self.get_adapters(force_refresh=True)

        verified = []
        for a in all_adapters:
            if a.status.lower() != "up":
                continue
            if not a.ipv4 or a.ipv4.startswith("127.") or a.ipv4.startswith("169.254."):
                continue
            if a.adapter_type == "virtual":
                continue
            # A valid upstream default gateway is mandatory for internet routing!
            if not a.gateway or a.gateway.startswith("0.0.0.0") or a.gateway.startswith("127."):
                continue

            a.is_internet_ready = True
            verified.append(a)

        # Fallback if no gateway found on strange tether configurations
        if not verified:
            for a in all_adapters:
                if a.status.lower() == "up" and a.ipv4 and not a.ipv4.startswith("127.") and not a.ipv4.startswith("169.254."):
                    if a.adapter_type != "virtual":
                        a.is_internet_ready = True
                        verified.append(a)

        return verified

    def _discover_windows(self) -> List[NetworkAdapter]:
        adapters: List[NetworkAdapter] = []
        ps_cmd = (
            "$ErrorActionPreference = 'SilentlyContinue'; "
            "$netAdapters = @{}; "
            "Get-NetAdapter | ForEach-Object { "
            "  $netAdapters[\"$($_.ifIndex)\"] = @{ "
            "    Name = $_.Name; "
            "    InterfaceDescription = $_.InterfaceDescription; "
            "    Status = $_.Status; "
            "    LinkSpeed = $_.LinkSpeed; "
            "    InterfaceIndex = [int]$_.ifIndex "
            "  } "
            "}; "
            "$ipConfigs = Get-NetIPConfiguration | ForEach-Object { "
            "  $idxStr = \"$($_.InterfaceIndex)\"; "
            "  $na = $netAdapters[$idxStr]; "
            "  $ipv4 = ($_.IPv4Address | Where-Object { $_.IPAddress -notlike '169.254*' -and $_.IPAddress -notlike '127*' } | Select-Object -First 1).IPAddress; "
            "  $ipv6 = ($_.IPv6Address | Select-Object -First 1).IPAddress; "
            "  $gw = ($_.IPv4DefaultGateway | Select-Object -First 1).NextHop; "
            "  [PSCustomObject]@{ "
            "    Name = if ($na) { $na.Name } else { $_.InterfaceAlias }; "
            "    Description = if ($na) { $na.InterfaceDescription } else { '' }; "
            "    Status = if ($na) { $na.Status } else { 'Up' }; "
            "    LinkSpeed = if ($na) { $na.LinkSpeed } else { '' }; "
            "    InterfaceIndex = [int]$_.InterfaceIndex; "
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
                        is_internet_ready=bool(gw and ipv4 and atype != "virtual"),
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
                    is_internet_ready=bool(ipv4 and not ipv4.startswith("127.") and atype != "virtual"),
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
                        is_internet_ready=(atype != "virtual"),
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
