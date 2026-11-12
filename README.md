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

**AetherBond** is a high-performance network bonding and link aggregation engine designed to overcome the historical pitfalls of multi-network downloaders. 

While tools like **Plexo** attempt to accelerate downloads by binding to local IP addresses, they fail on Windows due to the OS routing table's Weak Host model (Plexo Issue [#65](https://github.com/anmolkapil/plexo/issues/65)): packets bound only to an IP address still bleed out of the default gateway with the lowest metric (typically Ethernet), leaving Wi-Fi starved or causing TLS handshake drops.

**AetherBond completely solves this at the hardware level:**
1. **True Hardware NIC Route Steering**: Uses native Winsock `IP_UNICAST_IF` (option 31) with the physical interface index (`ifIndex`), bypassing Windows default routing bias. On Linux it sets `SO_BINDTODEVICE`; on macOS it sets `IP_BOUND_IF`.
2. **Dynamic Work-Stealing Range Chunker**: Partitions large files into concurrent byte-ranges. Fast connections automatically pull more work from the shared queue.
3. **Speculative Tail-End Chunk Racing**: Idle fast streams race lagging chunks near the end of a download to eliminate high-latency stalls.
4. **Transparent SOCKS5 & HTTP Multi-WAN Proxy**: Bonds Wi-Fi + Ethernet for **ANY application** (Chrome, Firefox, Steam, Epic Games, git, curl, torrent clients) by running a local multi-NIC proxy tunnel.
5. **Real-time Cyber-Glassmorphic Web UI**: Instant dashboard with live SVG/Canvas throughput waveforms, per-adapter metrics, and task controls.
6. **Built-in OS Network Doctor**: Detects and fixes Windows Connection Manager throttling (`fMinimizeConnections`) and weak-host conflicts.

---

## 📊 AetherBond vs. Plexo

| Feature | Plexo | **AetherBond** |
| :--- | :---: | :---: |
| **Windows Dual-NIC Support** | ❌ Broken (Issue #65: route bleed & handshake fails) | ✅ **Native `IP_UNICAST_IF` hardware steering** |
| **Multi-WAN Proxy Aggregator** | ❌ None (file downloader only) | ✅ **Built-in SOCKS5 (:1080) & HTTP (:8080) Proxy** |
| **Tail-End Chunk Racing** | Partial | ✅ **Speculative dynamic work-stealing & racing** |
| **Windows Routing Doctor** | ❌ None (manual gpedit required) | ✅ **`aetherbond doctor --fix` automatic audit** |
| **Application Footprint** | Heavy Electron GUI (~150 MB) | ✅ **Zero-bloat, instant CLI + Pure HTML5/Canvas UI** |
| **Cross-Platform Routing** | IP binding only | ✅ **Windows (`IP_UNICAST_IF`), Linux (`SO_BINDTODEVICE`), macOS (`IP_BOUND_IF`)** |
| **Resumable Downloads** | Basic | ✅ **Atomic `.aetherpart` state persistence + SHA-256** |

---

## 🚀 Quick Start

### 1. Installation

Clone and install directly in editable mode:

```bash
git clone https://github.com/SHAURYASANYAL3/AetherBond.git
cd AetherBond
pip install -e .
```

### 2. Check Hardware Interfaces & Bonding Readiness

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

### 3. Run High-Speed Accelerated Download

```bash
aetherbond download "https://example.com/largefile.iso" --streams 4
```

### 4. Launch the Transparent Multi-WAN Proxy

Route all your system applications, torrent clients, and browsers through both networks simultaneously:

```bash
aetherbond proxy --socks 1080 --http 8080
```
- Configure your app's proxy to `127.0.0.1:1080` (SOCKS5) or `127.0.0.1:8080` (HTTP).

### 5. Launch the Real-Time Web Dashboard

```bash
aetherbond web --port 8765
```
Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in any modern browser for real-time SVG/Canvas bandwidth graphs, per-adapter speedometer dials, and download management.

---

## 🩺 Windows Dual-Route Doctor

Windows by default can throttle or turn off Wi-Fi when an Ethernet cable is plugged in. Run AetherBond's built-in doctor to audit your network stack:

```bash
aetherbond doctor
```

To automatically configure Windows Connection Manager to permit concurrent Wi-Fi + Ethernet connections:

```bash
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

AetherBond includes a full unit test suite with mock range servers and socket validation:

```bash
python -m unittest discover -s tests
```

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

Developed with ⚡ by [SHAURYASANYAL3](https://github.com/SHAURYASANYAL3).
