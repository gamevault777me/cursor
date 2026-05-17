#!/usr/bin/env python3
"""Local browser dashboard for authorized Android device checks via ADB."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import android_device_check as device_check


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
ALLOWED_INSTALL_FLAGS = {"-d", "-g", "-t"}


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Android Device Control Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f172a;
      --panel: #111827;
      --panel-2: #1f2937;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --accent: #38bdf8;
      --ok: #34d399;
      --warn: #fbbf24;
      --bad: #fb7185;
      --border: #374151;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top, #1e293b, var(--bg) 42rem);
      color: var(--text);
    }
    header {
      padding: 2rem;
      border-bottom: 1px solid var(--border);
    }
    header h1 { margin: 0 0 .5rem; font-size: clamp(1.8rem, 4vw, 3rem); }
    header p { margin: 0; color: var(--muted); max-width: 68rem; line-height: 1.5; }
    main {
      display: grid;
      grid-template-columns: minmax(18rem, 26rem) 1fr;
      gap: 1rem;
      padding: 1rem;
    }
    section {
      background: rgba(17, 24, 39, .9);
      border: 1px solid var(--border);
      border-radius: 1rem;
      padding: 1rem;
      box-shadow: 0 20px 60px rgba(0,0,0,.25);
    }
    h2, h3 { margin-top: 0; }
    label {
      display: block;
      margin: .85rem 0 .35rem;
      color: var(--muted);
      font-size: .92rem;
    }
    input, select, button {
      width: 100%;
      border-radius: .65rem;
      border: 1px solid var(--border);
      background: #020617;
      color: var(--text);
      padding: .75rem .85rem;
      font: inherit;
    }
    button {
      margin-top: .75rem;
      border-color: #0369a1;
      background: linear-gradient(135deg, #0284c7, #0ea5e9);
      color: white;
      cursor: pointer;
      font-weight: 700;
    }
    button.secondary {
      background: #111827;
      border-color: var(--border);
    }
    button:disabled { opacity: .55; cursor: wait; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: .75rem; }
    .card {
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: .85rem;
      padding: .9rem;
      min-height: 5.2rem;
    }
    .card span {
      display: block;
      color: var(--muted);
      font-size: .8rem;
      margin-bottom: .35rem;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .value { font-size: 1.25rem; font-weight: 800; overflow-wrap: anywhere; }
    .status {
      display: inline-flex;
      align-items: center;
      gap: .45rem;
      margin-bottom: 1rem;
      color: var(--muted);
    }
    .dot {
      width: .7rem;
      height: .7rem;
      border-radius: 50%;
      background: var(--muted);
    }
    .dot.ok { background: var(--ok); }
    .dot.warn { background: var(--warn); }
    .dot.bad { background: var(--bad); }
    .checks {
      list-style: none;
      padding: 0;
      margin: .5rem 0 0;
    }
    .checks li {
      margin: .5rem 0;
      padding: .7rem .85rem;
      background: #020617;
      border: 1px solid var(--border);
      border-left: .25rem solid var(--accent);
      border-radius: .6rem;
    }
    pre {
      max-height: 34rem;
      overflow: auto;
      padding: 1rem;
      border-radius: .75rem;
      border: 1px solid var(--border);
      background: #020617;
      color: #c4b5fd;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .row { display: flex; align-items: center; gap: .7rem; }
    .row input[type="checkbox"] { width: auto; }
    .muted { color: var(--muted); }
    .danger { color: var(--bad); }
    @media (max-width: 820px) {
      main { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Android Device Control Dashboard</h1>
    <p>
      Local dashboard for authorized Android testing through ADB. Use it to inspect
      device health, look up app packages, and observe APK install results on devices
      you own or administer.
    </p>
  </header>
  <main>
    <section>
      <h2>Controller</h2>
      <div class="status"><span id="statusDot" class="dot"></span><span id="statusText">Ready</span></div>

      <button id="refreshDevices">Refresh connected devices</button>

      <label for="serial">ADB device</label>
      <select id="serial"></select>
      <p class="muted" id="deviceHint">Connect USB debugging or wireless debugging, then refresh.</p>

      <label for="packageName">Package name</label>
      <input id="packageName" placeholder="com.example.app">

      <button id="runCheck">Run health check</button>

      <h3 style="margin-top: 2rem;">Real-time status</h3>
      <p class="muted">Streams visible health snapshots from the selected authorized ADB device.</p>
      <label for="streamInterval">Refresh interval, seconds</label>
      <input id="streamInterval" type="number" min="2" max="60" value="5">
      <button id="startRealtime">Start real-time monitor</button>
      <button id="stopRealtime" class="secondary" disabled>Stop real-time monitor</button>

      <h3 style="margin-top: 2rem;">Optional APK install</h3>
      <p class="muted">APK path must exist on this controller machine.</p>
      <label for="apkPath">APK path</label>
      <input id="apkPath" placeholder="./app-debug.apk">
      <label>Install flags</label>
      <div class="row"><input id="flagD" type="checkbox" value="-d"><span>Allow downgrade (-d)</span></div>
      <div class="row"><input id="flagG" type="checkbox" value="-g"><span>Grant runtime permissions (-g)</span></div>
      <div class="row"><input id="flagT" type="checkbox" value="-t"><span>Allow test APKs (-t)</span></div>
      <div class="row" style="margin-top: .75rem;"><input id="clearLogcat" type="checkbox"><span>Clear logcat before install</span></div>
      <label for="logcatLines">Logcat lines after install</label>
      <input id="logcatLines" type="number" min="0" max="2000" value="300">
      <button id="installApk">Install and check</button>
    </section>

    <section>
      <h2>Device summary</h2>
      <div id="summary" class="grid">
        <div class="card"><span>Status</span><div class="value">No check yet</div></div>
      </div>
      <h3 style="margin-top: 1.5rem;">Health findings</h3>
      <ul id="findings" class="checks"><li>Run a health check to populate this section.</li></ul>
      <h3 style="margin-top: 1.5rem;">Raw result</h3>
      <pre id="raw">{}</pre>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    let realtimeSource = null;

    function setStatus(text, type = "") {
      $("statusText").textContent = text;
      $("statusDot").className = "dot " + type;
    }

    function selectedFlags() {
      return ["flagD", "flagG", "flagT"].filter((id) => $(id).checked).map((id) => $(id).value);
    }

    function selectedSerial() {
      return $("serial").value || "";
    }

    async function api(path, options = {}) {
      setStatus("Working...", "warn");
      const response = await fetch(path, {
        headers: {"Content-Type": "application/json"},
        ...options,
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || response.statusText);
      }
      setStatus("Ready", "ok");
      return payload;
    }

    function showError(error) {
      setStatus(error.message, "bad");
      $("findings").innerHTML = `<li class="danger">${escapeHtml(error.message)}</li>`;
      $("raw").textContent = JSON.stringify({error: error.message}, null, 2);
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function card(label, value) {
      return `<div class="card"><span>${escapeHtml(label)}</span><div class="value">${escapeHtml(value || "-")}</div></div>`;
    }

    function renderResult(payload) {
      const snapshot = payload.snapshot || payload.after || {};
      const build = snapshot.build || {};
      const battery = snapshot.battery || {};
      const storage = snapshot.storage || {};
      const packageInfo = snapshot.package || {};

      $("summary").innerHTML = [
        card("Device", `${build.manufacturer || ""} ${build.model || ""}`.trim()),
        card("Android", `${build.android_version || "-"} / SDK ${build.sdk || "-"}`),
        card("Security patch", build.security_patch),
        card("Battery", battery.level ? `${battery.level}%` : "-"),
        card("Temperature", battery.temperature ? `${Number(battery.temperature) / 10} C` : "-"),
        card("Package installed", packageInfo.package ? String(packageInfo.installed) : "not checked"),
        card("Storage", (storage.mounts || []).map((m) => `${m.mounted_on}: ${m.use_percent}`).join(", ")),
        card("Captured", snapshot.captured_at_utc),
        card("Serial", snapshot.serial),
      ].join("");

      const findings = payload.health_findings || [];
      $("findings").innerHTML = findings.map((finding) => `<li>${escapeHtml(finding)}</li>`).join("");
      $("raw").textContent = JSON.stringify(payload, null, 2);
    }

    async function refreshDevices() {
      try {
        const payload = await api("/api/devices");
        const devices = payload.devices || [];
        $("serial").innerHTML = "";
        if (devices.length === 0) {
          $("serial").innerHTML = "<option value=''>No devices found</option>";
          $("deviceHint").textContent = "No ADB devices found. Connect and authorize a device, then refresh.";
          return;
        }
        for (const device of devices) {
          const option = document.createElement("option");
          option.value = device.serial;
          option.textContent = `${device.serial} (${device.state}) ${device.model || ""}`;
          option.disabled = device.state !== "device";
          $("serial").appendChild(option);
        }
        $("deviceHint").textContent = `${devices.length} device(s) detected. Only authorized devices can be checked.`;
      } catch (error) {
        showError(error);
      }
    }

    async function runCheck() {
      try {
        const params = new URLSearchParams();
        if (selectedSerial()) params.set("serial", selectedSerial());
        if ($("packageName").value.trim()) params.set("package", $("packageName").value.trim());
        const payload = await api(`/api/check?${params.toString()}`);
        renderResult(payload);
      } catch (error) {
        showError(error);
      }
    }

    async function installApk() {
      try {
        const body = {
          serial: selectedSerial(),
          package: $("packageName").value.trim(),
          apk: $("apkPath").value.trim(),
          install_flags: selectedFlags(),
          clear_logcat: $("clearLogcat").checked,
          logcat_lines: Number($("logcatLines").value || 0),
        };
        const payload = await api("/api/install", {method: "POST", body: JSON.stringify(body)});
        renderResult(payload);
      } catch (error) {
        showError(error);
      }
    }

    function startRealtime() {
      stopRealtime();
      const params = new URLSearchParams();
      if (selectedSerial()) params.set("serial", selectedSerial());
      if ($("packageName").value.trim()) params.set("package", $("packageName").value.trim());
      params.set("interval", $("streamInterval").value || "5");
      realtimeSource = new EventSource(`/api/stream?${params.toString()}`);
      $("startRealtime").disabled = true;
      $("stopRealtime").disabled = false;
      setStatus("Real-time monitor connected", "ok");

      realtimeSource.addEventListener("snapshot", (event) => {
        renderResult(JSON.parse(event.data));
        setStatus("Real-time monitor running", "ok");
      });

      realtimeSource.addEventListener("error", (event) => {
        if (event.data) {
          showError(new Error(JSON.parse(event.data).error || "Real-time stream error"));
        } else {
          setStatus("Real-time stream disconnected", "bad");
        }
        stopRealtime();
      });

      realtimeSource.onerror = () => {
        setStatus("Real-time stream disconnected", "bad");
        stopRealtime();
      };
    }

    function stopRealtime() {
      if (realtimeSource) {
        realtimeSource.close();
        realtimeSource = null;
      }
      $("startRealtime").disabled = false;
      $("stopRealtime").disabled = true;
    }

    $("refreshDevices").addEventListener("click", refreshDevices);
    $("runCheck").addEventListener("click", runCheck);
    $("installApk").addEventListener("click", installApk);
    $("startRealtime").addEventListener("click", startRealtime);
    $("stopRealtime").addEventListener("click", () => {
      stopRealtime();
      setStatus("Real-time monitor stopped", "");
    });
    refreshDevices();
  </script>
</body>
</html>
"""


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def request_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def query_params(path: str) -> dict[str, str]:
    parsed = urlparse(path)
    params = parse_qs(parsed.query)
    return {key: values[-1] for key, values in params.items() if values}


def safe_int(value: Any, default: int = 0, minimum: int = 0, maximum: int = 2000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def normalize_install_flags(flags: Any) -> list[str]:
    if flags is None:
        return []
    if not isinstance(flags, list):
        raise ValueError("install_flags must be a list")
    normalized = [str(flag) for flag in flags]
    unsupported = sorted(set(normalized) - ALLOWED_INSTALL_FLAGS)
    if unsupported:
        allowed = ", ".join(sorted(ALLOWED_INSTALL_FLAGS))
        raise ValueError(f"Unsupported install flag(s): {', '.join(unsupported)}. Allowed: {allowed}")
    return normalized


def sse_bytes(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, sort_keys=True)
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AndroidDeviceDashboard/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(INDEX_HTML)
            return
        if parsed.path == "/api/devices":
            self.safe_json(self.handle_devices)
            return
        if parsed.path == "/api/check":
            self.safe_json(self.handle_check)
            return
        if parsed.path == "/api/stream":
            self.handle_stream()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/install":
            self.safe_json(self.handle_install)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_sse_headers(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def write_sse(self, event: str, payload: dict[str, Any]) -> None:
        self.wfile.write(sse_bytes(event, payload))
        self.wfile.flush()

    def safe_json(self, handler: Any) -> None:
        try:
            self.send_json(handler())
        except (SystemExit, ValueError, FileNotFoundError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except subprocess.TimeoutExpired as exc:
            self.send_json({"ok": False, "error": f"Command timed out: {' '.join(exc.cmd)}"}, HTTPStatus.REQUEST_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - include traceback for local lab debugging.
            self.send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def handle_devices(self) -> dict[str, Any]:
        device_check.require_adb()
        return {"ok": True, "devices": device_check.list_devices()}

    def handle_check(self) -> dict[str, Any]:
        params = query_params(self.path)
        package_name = params.get("package") or None
        serial = device_check.choose_device(params.get("serial") or None)
        snapshot = device_check.collect_snapshot(serial, package_name)
        return {
            "ok": True,
            "snapshot": snapshot,
            "health_findings": device_check.health_findings(snapshot),
        }

    def handle_stream(self) -> None:
        params = query_params(self.path)
        interval = safe_int(params.get("interval"), default=5, minimum=2, maximum=60)
        package_name = params.get("package") or None
        self.send_sse_headers()

        try:
            serial = device_check.choose_device(params.get("serial") or None)
            while True:
                snapshot = device_check.collect_snapshot(serial, package_name)
                self.write_sse(
                    "snapshot",
                    {
                        "ok": True,
                        "stream": {"interval_seconds": interval},
                        "snapshot": snapshot,
                        "health_findings": device_check.health_findings(snapshot),
                    },
                )
                time.sleep(interval)
        except (BrokenPipeError, ConnectionResetError):
            return
        except (SystemExit, ValueError, FileNotFoundError) as exc:
            self.write_sse("error", {"ok": False, "error": str(exc)})
        except subprocess.TimeoutExpired as exc:
            self.write_sse("error", {"ok": False, "error": f"Command timed out: {' '.join(exc.cmd)}"})
        except Exception as exc:  # noqa: BLE001 - include traceback for local lab debugging.
            self.write_sse(
                "error",
                {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )

    def handle_install(self) -> dict[str, Any]:
        body = request_body(self)
        apk = str(body.get("apk") or "").strip()
        if not apk:
            raise ValueError("apk is required")

        package_name = str(body.get("package") or "").strip() or None
        serial = device_check.choose_device(str(body.get("serial") or "").strip() or None)
        install_flags = normalize_install_flags(body.get("install_flags"))

        if bool(body.get("clear_logcat")):
            device_check.adb(serial, "logcat", "-c", timeout=15)

        before = device_check.collect_snapshot(serial, package_name)
        install_result = device_check.install_apk(serial, Path(apk), install_flags)
        after = device_check.collect_snapshot(serial, package_name)
        payload: dict[str, Any] = {
            "ok": True,
            "before": before,
            "after": after,
            "health_findings": device_check.health_findings(after),
            "install": install_result,
        }

        logcat_lines = safe_int(body.get("logcat_lines"), default=0)
        if logcat_lines > 0:
            payload["logcat"] = device_check.collect_logcat(serial, logcat_lines, package_name)
        return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start a local Android device control dashboard backed by authorized ADB."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host to bind. Defaults to {DEFAULT_HOST}.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to bind. Defaults to {DEFAULT_PORT}.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Android device control dashboard running at {url}")
    print("Use only with devices you own or are authorized to administer.")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print("Warning: this dashboard is bound beyond localhost; restrict network access.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
