#!/usr/bin/env python3
"""Android device information, health, app lookup, and APK install checks.

This script uses the Android Debug Bridge (adb) against an authorized device.
It is intended for local QA and lab testing on devices you own or administer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REPORT_DIR = Path("reports")


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def run(command: list[str], timeout: int = 30) -> CommandResult:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def require_adb() -> None:
    if shutil.which("adb") is None:
        raise SystemExit(
            "adb was not found. Install Android platform-tools and make sure adb is on PATH."
        )


def adb_command(serial: str | None, *args: str) -> list[str]:
    command = ["adb"]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    return command


def adb(serial: str | None, *args: str, timeout: int = 30) -> CommandResult:
    return run(adb_command(serial, *args), timeout=timeout)


def adb_shell(serial: str | None, command: str, timeout: int = 30) -> CommandResult:
    return adb(serial, "shell", command, timeout=timeout)


def list_devices() -> list[dict[str, str]]:
    result = adb(None, "devices", "-l")
    if result.returncode != 0:
        raise SystemExit(f"adb devices failed:\n{result.stderr or result.stdout}")

    devices: list[dict[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        serial = parts[0]
        state = parts[1] if len(parts) > 1 else "unknown"
        detail: dict[str, str] = {"serial": serial, "state": state}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                detail[key] = value
        devices.append(detail)
    return devices


def choose_device(serial: str | None) -> str:
    devices = list_devices()
    authorized = [device for device in devices if device.get("state") == "device"]

    if serial:
        matching = [device for device in devices if device["serial"] == serial]
        if not matching:
            raise SystemExit(f"No adb device found with serial {serial!r}.")
        if matching[0].get("state") != "device":
            raise SystemExit(
                f"Device {serial!r} is {matching[0].get('state')!r}; authorize it on the phone."
            )
        return serial

    if not authorized:
        if devices:
            states = ", ".join(f"{d['serial']}={d.get('state')}" for d in devices)
            raise SystemExit(f"No authorized adb device found. Connected devices: {states}")
        raise SystemExit("No adb devices found. Connect USB or use adb connect HOST:PORT.")

    if len(authorized) > 1:
        serials = ", ".join(device["serial"] for device in authorized)
        raise SystemExit(f"Multiple devices found ({serials}). Re-run with --serial SERIAL.")

    return authorized[0]["serial"]


def parse_key_value_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def getprop(serial: str, key: str) -> str:
    return adb_shell(serial, f"getprop {key}").stdout


def collect_build_info(serial: str) -> dict[str, str]:
    keys = {
        "manufacturer": "ro.product.manufacturer",
        "brand": "ro.product.brand",
        "model": "ro.product.model",
        "device": "ro.product.device",
        "android_version": "ro.build.version.release",
        "sdk": "ro.build.version.sdk",
        "security_patch": "ro.build.version.security_patch",
        "build_id": "ro.build.id",
        "fingerprint": "ro.build.fingerprint",
        "abi": "ro.product.cpu.abi",
        "bootloader": "ro.bootloader",
    }
    return {name: getprop(serial, prop) for name, prop in keys.items()}


def collect_battery(serial: str) -> dict[str, str]:
    return parse_key_value_lines(adb_shell(serial, "dumpsys battery").stdout)


def collect_storage(serial: str) -> dict[str, Any]:
    result = adb_shell(serial, "df -h /data /sdcard 2>/dev/null")
    rows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) < 6 or columns[0].lower().startswith("filesystem"):
            continue
        rows.append(
            {
                "filesystem": columns[0],
                "size": columns[1],
                "used": columns[2],
                "available": columns[3],
                "use_percent": columns[4],
                "mounted_on": columns[5],
            }
        )
    return {"raw": result.stdout, "mounts": rows}


def collect_memory(serial: str) -> dict[str, Any]:
    result = adb_shell(serial, "cat /proc/meminfo")
    wanted = {"MemTotal", "MemFree", "MemAvailable", "SwapTotal", "SwapFree"}
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key in wanted:
            parsed[key] = value.strip()
    return {"summary": parsed, "raw": result.stdout}


def collect_runtime(serial: str) -> dict[str, str]:
    commands = {
        "uptime": "uptime",
        "loadavg": "cat /proc/loadavg",
        "boot_completed": "getprop sys.boot_completed",
        "device_locked": "dumpsys trust | grep -i 'device locked' | head -n 1",
    }
    return {name: adb_shell(serial, command).stdout for name, command in commands.items()}


def collect_thermal(serial: str) -> dict[str, str]:
    result = adb_shell(serial, "dumpsys thermalservice", timeout=15)
    if result.returncode != 0 or not result.stdout:
        return {"raw": result.stderr or "thermalservice unavailable"}

    status_match = re.search(r"mStatus=(\w+)", result.stdout)
    head = "\n".join(result.stdout.splitlines()[:80])
    return {
        "status": status_match.group(1) if status_match else "unknown",
        "raw_excerpt": head,
    }


def collect_network(serial: str) -> dict[str, str]:
    commands = {
        "wifi": "dumpsys wifi | grep -E 'Wi-Fi is|mWifiInfo|SSID|BSSID|Supplicant state' | head -n 20",
        "ip_addresses": "ip addr show wlan0 2>/dev/null || ip addr",
    }
    return {name: adb_shell(serial, command, timeout=15).stdout for name, command in commands.items()}


def lookup_package(serial: str, package_name: str) -> dict[str, Any]:
    path = adb_shell(serial, f"pm path {package_name}")
    installed = path.returncode == 0 and bool(path.stdout)
    dump = adb_shell(serial, f"dumpsys package {package_name}", timeout=20) if installed else None
    version_name = ""
    version_code = ""
    first_install_time = ""
    last_update_time = ""

    if dump and dump.stdout:
        for line in dump.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("versionName="):
                version_name = stripped.split("=", 1)[1]
            elif stripped.startswith("versionCode="):
                version_code = stripped.split("=", 1)[1].split()[0]
            elif stripped.startswith("firstInstallTime="):
                first_install_time = stripped.split("=", 1)[1]
            elif stripped.startswith("lastUpdateTime="):
                last_update_time = stripped.split("=", 1)[1]

    return {
        "package": package_name,
        "installed": installed,
        "paths": path.stdout.splitlines() if path.stdout else [],
        "version_name": version_name,
        "version_code": version_code,
        "first_install_time": first_install_time,
        "last_update_time": last_update_time,
    }


def collect_snapshot(serial: str, package_name: str | None = None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "captured_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "serial": serial,
        "build": collect_build_info(serial),
        "battery": collect_battery(serial),
        "storage": collect_storage(serial),
        "memory": collect_memory(serial),
        "runtime": collect_runtime(serial),
        "thermal": collect_thermal(serial),
        "network": collect_network(serial),
    }
    if package_name:
        snapshot["package"] = lookup_package(serial, package_name)
    return snapshot


def parse_percent(value: str) -> int | None:
    match = re.search(r"(\d+)%", value)
    return int(match.group(1)) if match else None


def parse_int(value: str) -> int | None:
    match = re.search(r"-?\d+", value)
    return int(match.group(0)) if match else None


def health_findings(snapshot: dict[str, Any]) -> list[str]:
    findings: list[str] = []

    battery = snapshot.get("battery", {})
    level = parse_int(battery.get("level", ""))
    temp_tenths = parse_int(battery.get("temperature", ""))
    if level is not None and level < 20:
        findings.append(f"Battery is low ({level}%). Charge before longer testing.")
    if temp_tenths is not None and temp_tenths >= 450:
        findings.append(f"Battery temperature is high ({temp_tenths / 10:.1f} C). Let device cool.")

    for mount in snapshot.get("storage", {}).get("mounts", []):
        usage = parse_percent(mount.get("use_percent", ""))
        if usage is not None and usage >= 90:
            findings.append(
                f"Storage is nearly full on {mount.get('mounted_on')} ({mount.get('use_percent')})."
            )

    thermal_status = str(snapshot.get("thermal", {}).get("status", "")).lower()
    if thermal_status and thermal_status not in {"none", "0", "unknown"}:
        findings.append(f"Thermal status is {snapshot['thermal']['status']}.")

    boot_completed = snapshot.get("runtime", {}).get("boot_completed", "")
    if boot_completed and boot_completed != "1":
        findings.append("Boot has not fully completed yet.")

    return findings or ["No obvious health warnings detected from collected adb signals."]


def install_apk(serial: str, apk_path: Path, extra_flags: list[str]) -> dict[str, Any]:
    if not apk_path.exists():
        raise SystemExit(f"APK does not exist: {apk_path}")
    command = adb_command(serial, "install", "-r", *extra_flags, str(apk_path))
    result = run(command, timeout=180)
    return {
        "apk": str(apk_path),
        "command": " ".join(command),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "success": result.returncode == 0 and "Success" in (result.stdout + result.stderr),
    }


def collect_logcat(serial: str, lines: int, package_name: str | None = None) -> dict[str, str]:
    result = adb(serial, "logcat", "-d", "-t", str(lines), timeout=30)
    output = result.stdout
    if package_name:
        filtered = "\n".join(line for line in output.splitlines() if package_name in line)
    else:
        filtered = output
    return {
        "returncode": str(result.returncode),
        "raw_tail": output,
        "package_filtered": filtered,
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"android-device-check-{stamp}.json"
    md_path = output_dir / f"android-device-check-{stamp}.md"

    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: dict[str, Any]) -> str:
    device = report["after"]["build"]
    serial = report["after"]["serial"]
    lines = [
        "# Android Device Check",
        "",
        f"- Captured: {report['after']['captured_at_utc']}",
        f"- Serial: `{serial}`",
        f"- Device: {device.get('manufacturer')} {device.get('model')}",
        f"- Android: {device.get('android_version')} / SDK {device.get('sdk')}",
        f"- Security patch: {device.get('security_patch')}",
        "",
        "## Health findings",
        "",
    ]
    lines.extend(f"- {finding}" for finding in report["health_findings"])

    if report.get("install"):
        install = report["install"]
        lines.extend(
            [
                "",
                "## APK install",
                "",
                f"- APK: `{install['apk']}`",
                f"- Success: `{install['success']}`",
                f"- Return code: `{install['returncode']}`",
                "",
                "```text",
                install.get("stdout") or install.get("stderr") or "(no output)",
                "```",
            ]
        )

    package = report["after"].get("package")
    if package:
        lines.extend(
            [
                "",
                "## Package lookup",
                "",
                f"- Package: `{package['package']}`",
                f"- Installed: `{package['installed']}`",
                f"- Version name: `{package.get('version_name')}`",
                f"- Version code: `{package.get('version_code')}`",
                f"- First install: `{package.get('first_install_time')}`",
                f"- Last update: `{package.get('last_update_time')}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Battery",
            "",
            "```json",
            json.dumps(report["after"]["battery"], indent=2, sort_keys=True),
            "```",
            "",
            "## Storage",
            "",
            "```json",
            json.dumps(report["after"]["storage"].get("mounts", []), indent=2, sort_keys=True),
            "```",
            "",
            "## Memory summary",
            "",
            "```json",
            json.dumps(report["after"]["memory"].get("summary", {}), indent=2, sort_keys=True),
            "```",
        ]
    )

    if report.get("logcat"):
        logcat_text = report["logcat"].get("package_filtered") or report["logcat"].get("raw_tail") or ""
        lines.extend(
            [
                "",
                "## Logcat tail",
                "",
                "```text",
                logcat_text[-12000:],
                "```",
            ]
        )

    return "\n".join(lines) + "\n"


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    require_adb()
    serial = choose_device(args.serial)

    if args.clear_logcat:
        adb(serial, "logcat", "-c", timeout=15)

    before = collect_snapshot(serial, args.package)
    install_result = None
    if args.apk:
        install_result = install_apk(serial, Path(args.apk), args.install_flag)
    after = collect_snapshot(serial, args.package)

    report: dict[str, Any] = {
        "connection": {
            "method": "adb",
            "serial": serial,
            "note": "Authorized local USB or wireless debugging connection.",
        },
        "before": before,
        "after": after,
        "health_findings": health_findings(after),
        "install": install_result,
    }

    if args.logcat_lines > 0:
        report["logcat"] = collect_logcat(serial, args.logcat_lines, args.package)

    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Android device info, health signals, package lookup, and APK install results via adb."
    )
    parser.add_argument("--serial", help="adb device serial. Required only when multiple devices are connected.")
    parser.add_argument("--package", help="Application package name to look up, for example com.example.app.")
    parser.add_argument("--apk", help="Path to an APK to install with `adb install -r`.")
    parser.add_argument(
        "--install-flag",
        action="append",
        default=[],
        help="Extra flag passed to adb install. Repeat as needed, for example --install-flag=-d.",
    )
    parser.add_argument(
        "--clear-logcat",
        action="store_true",
        help="Clear logcat before collecting the pre-install snapshot/install/log tail.",
    )
    parser.add_argument(
        "--logcat-lines",
        type=int,
        default=0,
        help="Collect this many recent logcat lines after checks. Use 0 to disable.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.fspath(DEFAULT_REPORT_DIR),
        help="Directory for JSON and Markdown reports.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the full JSON report to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = build_report(args)
    json_path, md_path = write_reports(report, Path(args.output_dir))

    if args.print_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Report written:\n- {json_path}\n- {md_path}")
        for finding in report["health_findings"]:
            print(f"- {finding}")
        if report.get("install"):
            install = report["install"]
            print(f"Install success: {install['success']}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"Command timed out: {' '.join(exc.cmd)}") from exc
