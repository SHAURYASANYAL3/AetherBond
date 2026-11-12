<div align="center">

# ⚡ AetherBond

**Next-Generation Multi-WAN Link Aggregator & Dual-Interface Bandwidth Accelerator**

*Combine Wi-Fi and Ethernet in parallel with true hardware-level socket steering to unlock combined line speeds.*

[![GitHub License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-black.svg)](#)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Build Status](https://img.shields.io/badge/tests-passing-brightgreen.svg)](https://github.com/SHAURYASANYAL3/AetherBond/actions)

</div>

---

## ⚡ What is AetherBond?

**AetherBond** is a high-performance network bonding and link aggregation engine. Inspired by the vision of multi-network downloaders like **Plexo**, AetherBond was engineered from the ground up to empower users to take full, simultaneous advantage of multiple internet connections (such as **Wi-Fi + Ethernet** or **Wi-Fi + Cellular Hotspot**).

AetherBond combines parallel file chunking, low-level socket binding, dynamic work-stealing, and local proxy tunneling to maximize combined line throughput.

### 🌟 Key Highlights

1. **Hardware-Level NIC Steering**:
   - Uses native Winsock `IP_UNICAST_IF` (option 31) with the physical interface index (`ifIndex`) on Windows.
   - Uses `SO_BINDTODEVICE` on Linux and `IP_BOUND_IF` on macOS.
   - Guarantees outbound packets strictly traverse their intended hardware interface.

2. **Transparent Multi-WAN SOCKS5 & HTTP Proxy**:
   - Bonds Wi-Fi + Ethernet for **ANY application** on your computer.
   - Point your web browser, Steam, Epic Games, git, curl, or torrent client to `127.0.0.1:1080` (SOCKS5) or `127.0.0.1:8080` (HTTP) to aggregate bandwidth system-wide.

3. **Dynamic Work-Stealing Range Chunker**:
   - Automatically splits files into concurrent byte-ranges.
   - Faster connections dynamically grab and complete more chunks from the shared queue.

4. **Speculative Tail-End Chunk Racing**:
   - When only a few lagging chunks remain, idle streams race them concurrently on the fastest adapter to eliminate tail latency.

5. **Real-time Cyber-Glassmorphic Web Dashboard**:
   - Live 60 FPS Canvas throughput waveform displaying individual Wi-Fi, Ethernet, and aggregate bandwidth.
   - Per-adapter health status, speedometer gauges, and interactive task controls.

6. **Windows Network Doctor & Self-Healing Optimizer**:
   - Built-in `aetherbond doctor` utility that checks Windows Connection Manager policies (`fMinimizeConnections`) and interface metrics to ensure seamless dual-NIC operation.

---

## 🚀 Quick Start

### Option A: Standalone Executable (`.exe`)

Download `aetherbond.exe` from the [Releases](https://github.com/SHAURYASANYAL3/AetherBond/releases) section or build it locally. Run:

```cmd
aetherbond.exe status
aetherbond.exe download "https://example.com/largefile.iso"
aetherbond.exe web
```

### Option B: Python Package

```bash
git clone https://github.com/SHAURYASANYAL3/AetherBond.git
cd AetherBond
pip install -e .
```

---

## 📖 CLI Usage

### 1. Check Hardware Interfaces & Bonding Readiness

```bash
aetherbond status
```

Output:
```
Detected Hardware Interfaces:
--------------------------------------------------------------------------------
Interface                Type       ifIndex  IP Address         Link Speed   Status
--------------------------------------------------------------------------------
Wi-Fi                    WIFI       9        192.168.29.144     433 Mbps     Up
Ethernet                 ETHERNET   10       192.168.1.105      1.0 Gbps     Up
--------------------------------------------------------------------------------
✓ Multi-Link Aggregation READY: 2 verified internet adapters bonded:
  • Wi-Fi (192.168.29.144) [ifIndex 9]
  • Ethernet (192.168.1.105) [ifIndex 10]
```

### 2. High-Speed Accelerated Download

```bash
aetherbond download "https://example.com/largefile.iso" --streams 4
```

### 3. Launch the Transparent Multi-WAN Proxy Tunnel

Route all your system applications, torrent clients, and browsers through both networks simultaneously:

```bash
aetherbond proxy --socks 1080 --http 8080
```
- Configure your target application's proxy settings to `127.0.0.1:1080` (SOCKS5) or `127.0.0.1:8080` (HTTP).

### 4. Launch the Real-Time Web Dashboard

```bash
aetherbond web --port 8765
```
Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in any modern browser for real-time SVG/Canvas bandwidth graphs, per-adapter speedometer dials, and download management.

### 5. Windows Network Doctor

Audit and optimize Windows dual-interface policies:

```bash
aetherbond doctor
aetherbond doctor --fix
```

---

## 🛠️ Architecture

```
                       ┌────────────────────────┐
                       │     AetherBond CLI     │
                       │   & Web Dashboard UI   │
                       └───────────┬────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
   ┌──────────────────────┐                  ┌──────────────────────┐
   │ Turbo Range Downloader│                  │   Multi-NIC Proxy    │
   │  Dynamic Work Steal  │                  │  (SOCKS5 / HTTP :80) │
   └──────────┬───────────┘                  └──────────┬───────────┘
              │                                         │
              └────────────────────┬────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │ Hardware-Bound Socket Engine│
                    │   (IP_UNICAST_IF ifIndex)   │
                    └──────────────┬──────────────┘
                                   │
                 ┌─────────────────┴─────────────────┐
                 ▼                                   ▼
        ┌─────────────────┐                 ┌─────────────────┐
        │  NIC 1: Wi-Fi   │                 │ NIC 2: Ethernet │
        │ (192.168.29.x)  │                 │ (192.168.1.x)   │
        └────────┬────────┘                 └────────┬────────┘
                 │                                   │
                 └─────────────────┬─────────────────┘
                                   ▼
                    [ COMBINED AGGREGATED SPEED ]
```

---

## 🧪 Running Tests

AetherBond includes a comprehensive unit test suite:

```bash
python -m unittest discover -s tests
```

---

## 💡 Acknowledgements & Inspiration

AetherBond is inspired by the pioneering concepts of multi-network downloaders like **Plexo**, reimagined with low-level socket binding, system-wide proxy support, and real-time telemetry.

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

Developed with ⚡ by [SHAURYASANYAL3](https://github.com/SHAURYASANYAL3).
