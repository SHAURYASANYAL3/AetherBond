// AetherBond Real-Time Client Application
document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("speedChart");
  const ctx = canvas.getContext("2d");

  // Telemetry History for Waveform (60 seconds)
  const maxPoints = 60;
  const historyTotal = new Array(maxPoints).fill(0);
  const historyWifi = new Array(maxPoints).fill(0);
  const historyEth = new Array(maxPoints).fill(0);

  let currentAdapters = [];
  let isProxyRunning = false;

  // Format bytes helper
  function formatSpeed(bytesPerSec) {
    if (!bytesPerSec || bytesPerSec <= 0) return { val: "0.0", unit: "MB/s" };
    if (bytesPerSec >= 1024 * 1024 * 1024) {
      return { val: (bytesPerSec / (1024 ** 3)).toFixed(2), unit: "GB/s" };
    } else if (bytesPerSec >= 1024 * 1024) {
      return { val: (bytesPerSec / (1024 ** 2)).toFixed(2), unit: "MB/s" };
    } else if (bytesPerSec >= 1024) {
      return { val: (bytesPerSec / 1024).toFixed(1), unit: "KB/s" };
    }
    return { val: bytesPerSec.toFixed(0), unit: "B/s" };
  }

  function formatSize(bytes) {
    if (!bytes) return "0 B";
    if (bytes >= 1024 * 1024 * 1024) return (bytes / (1024 ** 3)).toFixed(2) + " GB";
    if (bytes >= 1024 * 1024) return (bytes / (1024 ** 2)).toFixed(2) + " MB";
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " KB";
    return bytes + " B";
  }

  function formatEta(seconds) {
    if (!seconds || seconds <= 0 || !isFinite(seconds)) return "Calculating...";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  // Draw real-time Canvas Waveform
  function drawWaveform() {
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
    ctx.lineWidth = 1;
    for (let y = 0; y < h; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Determine max speed scale
    const allSpeeds = [...historyTotal, ...historyWifi, ...historyEth];
    let maxVal = Math.max(...allSpeeds, 1024 * 1024 * 5); // default 5 MB/s baseline
    maxVal = maxVal * 1.15; // 15% headroom

    function plotLine(data, color, fillStyle) {
      ctx.beginPath();
      const step = w / (maxPoints - 1);
      data.forEach((val, i) => {
        const x = i * step;
        const y = h - (val / maxVal) * (h - 10);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.stroke();

      if (fillStyle) {
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.fillStyle = fillStyle;
        ctx.fill();
      }
    }

    // Wi-Fi (cyan)
    plotLine(historyWifi, "#00f0ff", "rgba(0, 240, 255, 0.05)");
    // Ethernet (purple)
    plotLine(historyEth, "#9d4edd", "rgba(157, 78, 221, 0.05)");
    // Total (neon green)
    plotLine(historyTotal, "#10b981", null);
  }

  // Connect to SSE Telemetry Stream
  function initSSE() {
    const sse = new EventSource("/events");

    sse.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleTelemetryUpdate(data);
      } catch (err) {
        console.error("Telemetry parse error", err);
      }
    };

    sse.onerror = () => {
      document.getElementById("status-text").innerText = "RECONNECTING";
      document.querySelector(".status-dot").style.background = "#f59e0b";
    };

    sse.onopen = () => {
      document.getElementById("status-text").innerText = "ONLINE";
      document.querySelector(".status-dot").style.background = "#10b981";
    };
  }

  function handleTelemetryUpdate(data) {
    currentAdapters = data.adapters || [];
    renderAdapters(currentAdapters);

    // Extract interface speeds
    let wifiSpeed = 0;
    let ethSpeed = 0;
    let totalSpeed = 0;

    const dl = data.download;
    const px = data.proxy;

    if (dl && dl.adapter_speeds) {
      for (const [name, spd] of Object.entries(dl.adapter_speeds)) {
        const lname = name.toLowerCase();
        if (lname.includes("wi-fi") || lname.includes("wifi") || lname.includes("wlan")) {
          wifiSpeed += spd;
        } else if (lname.includes("ethernet") || lname.includes("eth")) {
          ethSpeed += spd;
        }
      }
      totalSpeed += dl.total_speed_bps || 0;
    }

    if (px && px.adapter_speeds) {
      for (const [name, spd] of Object.entries(px.adapter_speeds)) {
        const lname = name.toLowerCase();
        if (lname.includes("wi-fi") || lname.includes("wifi") || lname.includes("wlan")) {
          wifiSpeed += spd;
        } else if (lname.includes("ethernet") || lname.includes("eth")) {
          ethSpeed += spd;
        }
      }
      totalSpeed += px.total_speed_bps || 0;
    }

    // Update Waveform data
    historyTotal.shift();
    historyTotal.push(totalSpeed);
    historyWifi.shift();
    historyWifi.push(wifiSpeed);
    historyEth.shift();
    historyEth.push(ethSpeed);
    drawWaveform();

    // Update Speed Cards
    const fmtTotal = formatSpeed(totalSpeed);
    document.getElementById("total-speed").innerHTML = `${fmtTotal.val} <span>${fmtTotal.unit}</span>`;

    const fmtWifi = formatSpeed(wifiSpeed);
    document.getElementById("wifi-speed").innerHTML = `${fmtWifi.val} <span>${fmtWifi.unit}</span>`;

    const fmtEth = formatSpeed(ethSpeed);
    document.getElementById("eth-speed").innerHTML = `${fmtEth.val} <span>${fmtEth.unit}</span>`;

    // Update Active Download Card
    const dlCard = document.getElementById("active-download-card");
    const emptyState = document.getElementById("no-download-placeholder");

    if (dl && !dl.is_completed) {
      dlCard.classList.remove("hidden");
      emptyState.classList.add("hidden");

      document.getElementById("task-filename").innerText = dl.filename;
      document.getElementById("task-percent").innerText = `${dl.progress_percent.toFixed(1)}%`;
      document.getElementById("task-fill").style.width = `${dl.progress_percent}%`;
      document.getElementById("task-transferred").innerText = `${formatSize(dl.downloaded_bytes)} / ${formatSize(dl.total_bytes)}`;
      document.getElementById("task-eta").innerText = `ETA: ${formatEta(dl.eta_seconds)}`;

      const currentSpeed = formatSpeed(dl.total_speed_bps);
      document.getElementById("task-current-speed").innerText = `${currentSpeed.val} ${currentSpeed.unit}`;

      document.getElementById("btn-pause").innerText = dl.is_paused ? "Resume" : "Pause";
    } else {
      dlCard.classList.add("hidden");
      emptyState.classList.remove("hidden");
    }

    // Update Proxy Card
    if (px) {
      isProxyRunning = px.is_running;
      document.getElementById("proxy-conns").innerText = px.active_connections;
      const fmtPxSpd = formatSpeed(px.total_speed_bps);
      document.getElementById("proxy-spd").innerText = `${fmtPxSpd.val} ${fmtPxSpd.unit}`;

      const pBadge = document.getElementById("proxy-badge");
      const pBtn = document.getElementById("btn-toggle-proxy");
      if (px.is_running) {
        pBadge.innerText = "ONLINE";
        pBadge.style.color = "var(--accent-green)";
        pBtn.innerText = "Stop Proxy Tunnel";
        pBtn.classList.add("btn-danger");
      } else {
        pBadge.innerText = "OFFLINE";
        pBadge.style.color = "var(--accent-yellow)";
        pBtn.innerText = "Start Aggregator Proxy";
        pBtn.classList.remove("btn-danger");
      }
    }
  }

  function renderAdapters(adapters) {
    const tbody = document.getElementById("adapters-tbody");
    if (!adapters || adapters.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center">No network adapters found</td></tr>';
      return;
    }

    tbody.innerHTML = adapters.map(a => {
      const isUp = a.status.toLowerCase() === "up";
      const isReady = a.is_internet_ready;
      return `
        <tr>
          <td><strong>${escapeHtml(a.name)}</strong></td>
          <td><span class="badge ${a.adapter_type === 'wifi' ? 'badge-wifi' : 'badge-eth'}">${a.adapter_type.toUpperCase()}</span></td>
          <td><code>${a.if_index}</code></td>
          <td>${a.ipv4 || '<span class="text-dim">None</span>'}</td>
          <td>${a.gateway || '<span class="text-dim">--</span>'}</td>
          <td>${a.speed_display}</td>
          <td><span class="${isUp ? 'text-green' : 'text-red'}">● ${a.status}</span></td>
          <td>${isReady ? '<span class="badge badge-accent">BONDED</span>' : '<span class="text-dim">Standby</span>'}</td>
        </tr>
      `;
    }).join("");

    // Update NIC sub-labels on cards
    const wifi = adapters.find(a => a.adapter_type === 'wifi' && a.status.toLowerCase() === 'up');
    if (wifi) {
      document.getElementById("wifi-nic-name").innerText = `${wifi.name} (ifIndex ${wifi.if_index})`;
    }
    const eth = adapters.find(a => a.adapter_type === 'ethernet' && a.status.toLowerCase() === 'up');
    if (eth) {
      document.getElementById("eth-nic-name").innerText = `${eth.name} (ifIndex ${eth.if_index})`;
    }
  }

  function escapeHtml(str) {
    return (str || "").replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]);
  }

  // Event Listeners: Download Form
  document.getElementById("download-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = document.getElementById("dl-url").value.trim();
    const threads = parseInt(document.getElementById("dl-threads").value, 10) || 4;
    if (!url) return;

    try {
      const res = await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, threads })
      });
      const data = await res.json();
      console.log("Download triggered:", data);
    } catch (err) {
      alert("Failed to start download: " + err);
    }
  });

  // Event Listeners: Pause / Resume / Cancel
  document.getElementById("btn-pause").addEventListener("click", async () => {
    const btn = document.getElementById("btn-pause");
    const isPaused = btn.innerText === "Resume";
    await fetch(isPaused ? "/api/resume" : "/api/pause", { method: "POST" });
  });

  document.getElementById("btn-cancel").addEventListener("click", async () => {
    if (confirm("Are you sure you want to cancel the current download?")) {
      await fetch("/api/cancel", { method: "POST" });
    }
  });

  // Event Listeners: Toggle Proxy
  document.getElementById("btn-toggle-proxy").addEventListener("click", async () => {
    const endpoint = isProxyRunning ? "/api/proxy/stop" : "/api/proxy/start";
    await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ socks_port: 1080, http_port: 8080 })
    });
  });

  // Event Listeners: Doctor Modal
  const modal = document.getElementById("doctor-modal");
  document.getElementById("btn-doctor").addEventListener("click", async () => {
    modal.classList.remove("hidden");
    const body = document.getElementById("doctor-report");
    body.innerHTML = "<p>Running network and routing diagnostics...</p>";

    try {
      const res = await fetch("/api/doctor");
      const rep = await res.json();
      let html = `<p><strong>Platform:</strong> ${rep.platform}</p>`;
      if (rep.issues.length === 0) {
        html += `<p class="text-green" style="margin-top: 10px;"><strong>✓ System is fully optimized for multi-NIC aggregation!</strong></p>`;
      } else {
        html += `<div style="margin-top: 10px;"><strong class="text-red">Issues Detected:</strong><ul>`;
        rep.issues.forEach(i => html += `<li>${i}</li>`);
        html += `</ul></div>`;
      }

      if (rep.recommendations.length > 0) {
        html += `<div style="margin-top: 10px;"><strong>Recommendations:</strong><ul>`;
        rep.recommendations.forEach(r => html += `<li>${r}</li>`);
        html += `</ul></div>`;
      }
      body.innerHTML = html;
    } catch (err) {
      body.innerHTML = `<p class="text-red">Doctor scan failed: ${err}</p>`;
    }
  });

  document.getElementById("btn-close-doctor").addEventListener("click", () => {
    modal.classList.add("hidden");
  });

  document.getElementById("btn-refresh-adapters").addEventListener("click", async () => {
    const res = await fetch("/api/adapters");
    const data = await res.json();
    renderAdapters(data);
  });

  // Initialize
  initSSE();
  drawWaveform();
});
