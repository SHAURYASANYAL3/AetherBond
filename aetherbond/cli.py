"""
AetherBond Unified Command Line Interface
Multi-WAN Dual-Link Aggregation & Turbo Download Engine
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

# Ensure Windows terminal outputs UTF-8 cleanly without charmap errors
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from aetherbond.core.adapter import AdapterManager
from aetherbond.core.downloader import DownloadStatus, TurboDownloader
from aetherbond.core.optimizer import SystemOptimizer
from aetherbond.core.proxy import MultiNicProxy
from aetherbond.utils.formatting import format_bytes_size, format_bytes_speed, render_progress_bar
from aetherbond.utils.logger import BOLD, CYAN, GREEN, MAGENTA, RED, RESET, YELLOW, setup_logger
from aetherbond.web.server import run_web_dashboard


def print_banner():
    banner = f"""{CYAN}{BOLD}
    █████╗ ███████╗████████╗██╗  ██╗███████╗██████╗ ██████╗  ██████╗ ███╗   ██╗██████╗ 
   ██╔══██╗██╔════╝╚══██╔══╝██║  ██║██╔════╝██╔══██╗██╔══██╗██╔═══██╗████╗  ██║██╔══██╗
   ███████║█████╗     ██║   ███████║█████╗  ██████╔╝██████╔╝██║   ██║██╔██╗ ██║██║  ██║
   ██╔══██║██╔══╝     ██║   ██╔══██║██╔══╝  ██╔══██╗██╔══██╗██║   ██║██║╚██╗██║██║  ██║
   ██║  ██║███████╗   ██║   ██║  ██║███████╗██║  ██║██████╔╝╚██████╔╝██║ ╚████║██████╔╝
   ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚═════╝ 
{RESET}{MAGENTA}   Multi-WAN Dual-NIC Link Aggregation Engine (Wi-Fi + Ethernet) | v2.0.0{RESET}
"""
    print(banner)


def cmd_status(args):
    print_banner()
    mgr = AdapterManager()
    adapters = mgr.get_adapters(force_refresh=True)

    print(f"{BOLD}Detected Hardware Interfaces:{RESET}")
    print("-" * 80)
    print(f"{'Interface':<24} {'Type':<10} {'ifIndex':<8} {'IP Address':<18} {'Link Speed':<12} {'Status'}")
    print("-" * 80)

    for a in adapters:
        atype_color = CYAN if a.adapter_type == "wifi" else (MAGENTA if a.adapter_type == "ethernet" else RESET)
        status_color = GREEN if a.status.lower() == "up" else RED
        print(
            f"{a.name:<24} {atype_color}{a.adapter_type.upper():<10}{RESET} {a.if_index:<8} "
            f"{str(a.ipv4 or '--'):<18} {a.speed_display:<12} {status_color}{a.status}{RESET}"
        )

    print("-" * 80)
    bondable = mgr.get_bondable_adapters(verify_ping=True)
    if len(bondable) >= 2:
        print(f"\n{GREEN}{BOLD}✓ Multi-Link Aggregation READY:{RESET} {len(bondable)} verified internet adapters bonded:")
        for b in bondable:
            print(f"  • {b.name} ({b.ipv4}) [ifIndex {b.if_index}]")
    elif len(bondable) == 1:
        print(f"\n{YELLOW}{BOLD}! Single Active Adapter Detected:{RESET} {bondable[0].name} ({bondable[0].ipv4})")
        print(f"  Connect Ethernet alongside Wi-Fi (or USB Phone Tethering) to unlock dual-pipe combined speed.")
    else:
        print(f"\n{RED}{BOLD}✗ No active internet-ready adapters found.{RESET}")


def cmd_download(args):
    print_banner()
    url = args.url
    output_dir = args.output
    streams = args.streams

    mgr = AdapterManager()
    bondable = mgr.get_bondable_adapters(verify_ping=True)
    if not bondable:
        print(f"{YELLOW}Warning: No verified dual adapters, probing all available...{RESET}")
        bondable = mgr.get_adapters()

    print(f"{BOLD}Target URL:{RESET} {url}")
    print(f"{BOLD}Streams per Interface:{RESET} {streams}")
    print(f"{BOLD}Bonded Adapters ({len(bondable)}):{RESET} {', '.join(a.name for a in bondable)}")
    print()

    last_line_len = 0

    def progress_callback(st: DownloadStatus):
        nonlocal last_line_len
        bar = render_progress_bar(st.progress_percent, length=20)
        spd_str = format_bytes_speed(st.total_speed_bps)
        downloaded_str = format_bytes_size(st.downloaded_bytes)
        total_str = format_bytes_size(st.total_bytes)

        eta_str = f"{int(st.eta_seconds)}s" if st.eta_seconds else "--"

        # Per adapter breakdown
        per_nic = " | ".join(
            f"{name}: {format_bytes_speed(spd)}"
            for name, spd in st.adapter_speeds.items()
            if spd > 0
        )
        if not per_nic:
            per_nic = "Aggregating streams..."

        line = (
            f"\r{CYAN}[{bar}]{RESET} {st.progress_percent:>5.1f}% | "
            f"{downloaded_str}/{total_str} | {GREEN}{spd_str}{RESET} | ETA: {eta_str} | ({per_nic})"
        )

        sys.stdout.write(line.ljust(last_line_len))
        sys.stdout.flush()
        last_line_len = len(line)

    downloader = TurboDownloader(
        url=url,
        output_dir=output_dir,
        filename=args.name,
        adapters=bondable,
        streams_per_adapter=streams,
        on_progress=progress_callback,
    )

    start_t = time.time()
    success = downloader.start(blocking=True)
    elapsed = max(0.1, time.time() - start_t)

    print()
    if success:
        total_sz = downloader.chunk_engine.total_size if downloader.chunk_engine else 0
        avg_speed = total_sz / elapsed
        print(f"\n{GREEN}{BOLD}✓ Download Completed Successfully!{RESET}")
        print(f"  Target:   {downloader.target_path}")
        print(f"  Size:     {format_bytes_size(total_sz)}")
        print(f"  Duration: {elapsed:.1f}s (Average Speed: {format_bytes_speed(avg_speed)})")
        if downloader.sha256_checksum:
            print(f"  SHA-256:  {downloader.sha256_checksum}")
    else:
        print(f"\n{RED}{BOLD}✗ Download Failed or was Aborted.{RESET}")


def cmd_proxy(args):
    print_banner()
    socks_port = args.socks
    http_port = args.http

    print(f"{GREEN}{BOLD}Starting Transparent Multi-WAN Proxy Tunnel...{RESET}")
    print(f" • SOCKS5 Proxy: {CYAN}127.0.0.1:{socks_port}{RESET}")
    print(f" • HTTP Proxy:   {CYAN}127.0.0.1:{http_port}{RESET}")
    print("\nApplications configured to use this proxy will automatically route connections")
    print("across all active hardware interfaces (Wi-Fi + Ethernet) in parallel.")
    print("\nPress Ctrl+C to terminate.")

    proxy = MultiNicProxy(socks5_port=socks_port, http_port=http_port)
    proxy.start(blocking=True)


def cmd_doctor(args):
    print_banner()
    print(f"{BOLD}Running Operating System Multi-NIC Diagnostics...{RESET}\n")

    diag = SystemOptimizer.diagnose()
    print(f"Operating System: {diag['platform']}")

    if diag["issues"]:
        print(f"\n{RED}{BOLD}Issues Detected:{RESET}")
        for iss in diag["issues"]:
            print(f" ✗ {iss}")
    else:
        print(f"\n{GREEN}{BOLD}✓ No routing conflicts detected in operating system policy.{RESET}")

    if diag["recommendations"]:
        print(f"\n{YELLOW}{BOLD}Recommendations:{RESET}")
        for rec in diag["recommendations"]:
            print(f" • {rec}")

    if args.fix:
        print(f"\n{CYAN}Attempting to apply automatic policy fix...{RESET}")
        ok, msg = SystemOptimizer.apply_windows_dual_nic_fix()
        if ok:
            print(f"{GREEN}✓ {msg}{RESET}")
        else:
            print(f"{RED}✗ {msg}{RESET}")


def cmd_web(args):
    print_banner()
    port = args.port
    print(f"{GREEN}{BOLD}Launching AetherBond Web Dashboard...{RESET}")
    print(f"Access UI at: {CYAN}http://127.0.0.1:{port}{RESET}")
    print("Press Ctrl+C to stop.")
    run_web_dashboard(port=port, blocking=True)


def main():
    setup_logger()

    parser = argparse.ArgumentParser(
        prog="aetherbond",
        description="AetherBond: Multi-WAN Dual-Link Aggregation & Turbo Network Bonding Engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # download
    p_dl = subparsers.add_parser("download", help="Accelerate file download bonding Wi-Fi + Ethernet")
    p_dl.add_argument("url", help="URL of the file to download")
    p_dl.add_argument("-o", "--output", default=".", help="Target download directory")
    p_dl.add_argument("-n", "--name", default=None, help="Custom output filename")
    p_dl.add_argument("-s", "--streams", type=int, default=4, help="Concurrent streams per adapter")

    # proxy
    p_px = subparsers.add_parser("proxy", help="Run local Multi-NIC SOCKS5 & HTTP Aggregator Proxy")
    p_px.add_argument("--socks", type=int, default=1080, help="SOCKS5 port (default: 1080)")
    p_px.add_argument("--http", type=int, default=8080, help="HTTP CONNECT port (default: 8080)")

    # status
    subparsers.add_parser("status", help="Inspect active hardware interfaces and bonding capability")

    # doctor
    p_doc = subparsers.add_parser("doctor", help="Diagnose and optimize Windows dual-NIC routing")
    p_doc.add_argument("--fix", action="store_true", help="Automatically apply registry optimization")

    # web
    p_web = subparsers.add_parser("web", help="Start the real-time Cyber-Glassmorphic Web UI")
    p_web.add_argument("-p", "--port", type=int, default=8765, help="Web server port (default: 8765)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "status": cmd_status,
        "download": cmd_download,
        "proxy": cmd_proxy,
        "doctor": cmd_doctor,
        "web": cmd_web,
    }

    fn = dispatch.get(args.command)
    if fn:
        try:
            fn(args)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Terminated by user.{RESET}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
