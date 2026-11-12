<div align="center">

# ⚡ AetherBond

**Next-Generation Multi-WAN Link Aggregator & Dual-Interface Bandwidth Accelerator**

*Combine Wi-Fi, Ethernet, and Mobile USB Tethering in parallel with true hardware-level socket steering to unlock combined line speeds.*

[![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-black.svg)](#)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Release](https://img.shields.io/badge/release-v2.1.0-blueviolet.svg)](https://github.com/SHAURYASANYAL3/AetherBond/releases)

</div>

---

## ⚡ What is AetherBond?

**AetherBond** is a high-performance network bonding and link aggregation desktop application. Inspired by the pioneering concepts of multi-network downloaders like **Plexo**, AetherBond was engineered from the ground up to empower users to take full, simultaneous advantage of multiple internet connections (**Wi-Fi + Ethernet**, **Wi-Fi + Phone USB Tethering**, or dual LANs) at full combined throughput.

Built with a true **Native Desktop GUI** (Windows 11 Cyber-Obsidian Fluent UI) following strict **UI/UX Pro Max** standards, AetherBond features zero web-browser dependency, hardware-level socket routing, and real-time per-adapter controls.

---

## 🌟 Key Highlights

1. **100% Native Desktop Application**:
   - Double-click `aetherbond.exe` to launch a sleek, standalone Windows 11 Fluent dark-mode desktop window.
   - Built with high-contrast Cyber-Obsidian styling, 44px tactile click targets, and 60 FPS Canvas telemetry waveforms.

2. **True Hardware-Level NIC Steering**:
   - Uses native Winsock `IP_UNICAST_IF` (option 31) with each physical interface index (`ifIndex`) on Windows.
   - Uses `SO_BINDTODEVICE` on Linux and `IP_BOUND_IF` on macOS.
   - Guarantees outbound packets strictly traverse their intended hardware interface without route leakage.

3. **Hot-Plug & USB Phone Tethering Support**:
   - Plug in your Android phone (Remote NDIS) or iPhone (Apple Mobile Device Ethernet) over USB.
   - AetherBond instantly auto-detects the new interface and hot-plugs it into the bonded stream pool without restarting the app or download.

4. **Transparent Multi-WAN SOCKS5 & HTTP Proxy**:
   - Bonds Wi-Fi + Ethernet for **ANY application** on your computer.
   - Point your web browser, Steam, Epic Games, git, curl, or torrent client to `127.0.0.1:1080` (SOCKS5) or `127.0.0.1:8080` (HTTP) to aggregate bandwidth system-wide.

5. **Dynamic Work-Stealing Range Chunker & Tail-End Racing**:
   - Automatically splits files into concurrent byte-ranges.
   - Faster connections dynamically grab and complete more chunks from the shared queue.
   - Speculative tail racing ensures lagging packets near the end of a download never stall completion.

6. **Windows Network Doctor & Self-Healing Optimizer**:
   - Built-in `aetherbond doctor` utility that checks Windows Connection Manager policies (`fMinimizeConnections`) and interface metrics to ensure seamless dual-NIC operation.

---

## 🚀 Quick Start

### Standalone Executable (`aetherbond.exe`)

Download `aetherbond.exe` from the [Releases](https://github.com/SHAURYASANYAL3/AetherBond/releases) section:
1. Double-click `aetherbond.exe` to launch the **Native Desktop Application**.
2. Select your active adapters (Wi-Fi and Ethernet / Phone USB).
3. Paste any download URL and click **⚡ START BONDED DOWNLOAD**!

---

## 📖 CLI Usage

AetherBond can also be run entirely from PowerShell or Terminal:

```bash
# Launch Native Desktop GUI
aetherbond gui

# Check active hardware adapters
aetherbond status

# High-Speed Multi-NIC Download
aetherbond download "https://example.com/largefile.iso" --streams 4

# Start the Multi-WAN Proxy Tunnel
aetherbond proxy --socks 1080 --http 8080

# Audit and optimize Windows dual-interface policies
aetherbond doctor --fix
```

---

## 💡 Acknowledgements & Inspiration

AetherBond is inspired by the pioneering concepts of multi-network downloaders like **Plexo**, reimagined as a full native desktop application with hardware-level socket steering, system-wide proxy support, and real-time telemetry.

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

Developed with ⚡ by [SHAURYASANYAL3](https://github.com/SHAURYASANYAL3).
