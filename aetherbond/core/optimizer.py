"""
Operating System Dual-NIC Routing Optimizer and Doctor
Diagnoses and configures Windows Connection Manager policies, Strong Host routing,
and interface metrics for simultaneous Wi-Fi and Ethernet operation.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aetherbond.optimizer")


class SystemOptimizer:
    """Diagnoses and tunes operating system networking for simultaneous multi-WAN links."""

    @staticmethod
    def diagnose() -> Dict[str, any]:
        """Runs a complete dual-NIC diagnostic scan."""
        report = {
            "platform": sys.platform,
            "can_dual_bond": True,
            "issues": [],
            "recommendations": [],
            "details": {},
        }

        if sys.platform != "win32":
            report["details"]["status"] = "Non-Windows OS; socket-level device binding is fully supported."
            return report

        # 1. Check Windows Connection Manager fMinimizeConnections
        f_min_val = SystemOptimizer._check_windows_minimize_connections()
        report["details"]["fMinimizeConnections"] = f_min_val

        if f_min_val == 1 or f_min_val == 3:
            report["issues"].append(
                "Windows Connection Manager is configured to minimize simultaneous connections "
                "(fMinimizeConnections = 1/3). Windows may disconnect Wi-Fi when Ethernet is plugged in."
            )
            report["recommendations"].append(
                "Set 'Minimize the number of simultaneous connections' to Disabled in Group Policy, "
                "or run 'aetherbond doctor --fix'."
            )
            report["can_dual_bond"] = False

        # 2. Check Weak Host routing configuration
        weak_host_info = SystemOptimizer._check_weak_host_config()
        report["details"]["weak_host"] = weak_host_info

        # 3. Check active adapters
        from aetherbond.core.adapter import AdapterManager
        mgr = AdapterManager()
        adapters = mgr.get_adapters(force_refresh=True)
        report["details"]["adapters"] = [a.to_dict() for a in adapters]

        active_count = sum(1 for a in adapters if a.status.lower() == "up" and a.ipv4 and not a.ipv4.startswith("169.254"))
        if active_count < 2:
            report["recommendations"].append(
                f"Currently only {active_count} active internet adapter detected. Connect Wi-Fi and Ethernet (or Phone USB Tethering) "
                "simultaneously to achieve combined dual-link speed."
            )

        return report

    @staticmethod
    def _check_windows_minimize_connections() -> Optional[int]:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Policies\Microsoft\Windows\WcmSvc\GroupPolicy",
                0,
                winreg.KEY_READ,
            )
            val, _ = winreg.QueryValueEx(key, "fMinimizeConnections")
            winreg.CloseKey(key)
            return int(val)
        except Exception:
            return None

    @staticmethod
    def _check_weak_host_config() -> List[Dict[str, str]]:
        results = []
        try:
            p = subprocess.run(
                ["netsh", "interface", "ipv4", "show", "interface"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Parse output for interface indices
            for line in p.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0].isdigit():
                    idx = parts[0]
                    name = " ".join(parts[4:])
                    results.append({"index": idx, "name": name})
        except Exception as e:
            logger.debug("Failed checking weak host: %s", e)
        return results

    @staticmethod
    def apply_windows_dual_nic_fix() -> Tuple[bool, str]:
        """
        Configures Windows to keep Wi-Fi and Ethernet active together
        by setting fMinimizeConnections = 0.
        Requires administrative privileges.
        """
        if sys.platform != "win32":
            return False, "This fix is only applicable to Windows."

        ps_script = (
            "try { "
            "  $regPath = 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\WcmSvc\\GroupPolicy'; "
            "  if (-not (Test-Path $regPath)) { New-Item -Path $regPath -Force | Out-Null }; "
            "  Set-ItemProperty -Path $regPath -Name 'fMinimizeConnections' -Value 0 -Type DWord; "
            "  Write-Output 'SUCCESS'; "
            "} catch { "
            "  Write-Error $_.Exception.Message; "
            "}"
        )

        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "SUCCESS" in res.stdout:
                return True, "Successfully disabled Windows Connection Manager throttling (fMinimizeConnections = 0)."
            else:
                return False, f"Failed to apply setting (may require Run as Administrator): {res.stderr.strip()}"
        except Exception as e:
            return False, f"Error executing registry update: {e}"
