# Android Device Check

This repository contains a small ADB-based utility for checking how an Android
device looks before and after testing a new application.

The tool is designed for devices you own or are authorized to administer. It
uses Android Debug Bridge (ADB) over USB or Android's approved wireless
debugging flow. It does not create a hidden command-and-control channel.

## What it checks

- Connected device identity and build information
- Android version, SDK level, security patch, ABI, and build fingerprint
- Battery level, charging state, and temperature
- Storage usage for `/data` and `/sdcard`
- Memory summary from `/proc/meminfo`
- Runtime signals such as uptime, boot completion, load average, and lock state
- Thermal service status where available
- Wi-Fi/IP details where available
- Optional app package lookup
- Optional APK install result
- Optional logcat tail after installation

## Requirements

Install Android platform-tools so `adb` is available on your `PATH`.

On Ubuntu/Debian:

```bash
sudo apt update
sudo apt install android-tools-adb
```

Or install the latest official platform-tools from:

<https://developer.android.com/tools/releases/platform-tools>

## Connect a device

### USB debugging

1. On the Android device, enable **Developer options**.
2. Enable **USB debugging**.
3. Connect the device with USB.
4. Accept the RSA authorization prompt on the device.
5. Confirm the device is visible:

```bash
adb devices -l
```

### Wireless debugging

Use Android's built-in wireless debugging pairing flow:

1. On the device, open **Developer options > Wireless debugging**.
2. Pair the computer:

```bash
adb pair DEVICE_IP:PAIR_PORT
```

3. Connect to the device:

```bash
adb connect DEVICE_IP:CONNECT_PORT
adb devices -l
```

## Run a health check

```bash
python3 scripts/android_device_check.py
```

Reports are written to `reports/` as both JSON and Markdown.

## Run the browser control dashboard

Start the local dashboard:

```bash
python3 scripts/android_dashboard.py
```

Then open:

```text
http://127.0.0.1:8765/
```

The dashboard lets you:

- Refresh and select authorized ADB devices
- Run the same device health check from a browser
- Look up an installed package
- Install an APK from a path on the controller machine
- Capture recent logcat output after install
- View the raw JSON result for troubleshooting

By default the dashboard binds to `127.0.0.1`, so it is only reachable from the
controller computer. If you deliberately bind it to another host, protect that
machine and network because anyone with dashboard access can run ADB checks on
authorized connected devices.

```bash
python3 scripts/android_dashboard.py --host 127.0.0.1 --port 8765
```

## Look up an installed app

```bash
python3 scripts/android_device_check.py --package com.example.app
```

The report includes whether the package is installed, APK paths, version name,
version code, first install time, and last update time.

## Test installing a new APK

```bash
python3 scripts/android_device_check.py \
  --apk ./app-debug.apk \
  --package com.example.app \
  --clear-logcat \
  --logcat-lines 300
```

The utility captures a snapshot, installs with `adb install -r`, captures a
second snapshot, and records the install output. If `--package` is provided,
the report also verifies the package after installation and filters logcat lines
that mention the package.

If several devices are connected, pass the serial shown by `adb devices -l`:

```bash
python3 scripts/android_device_check.py --serial SERIAL --package com.example.app
```

## Helpful install flags

Pass additional `adb install` flags with repeated `--install-flag` options:

```bash
python3 scripts/android_device_check.py \
  --apk ./app-debug.apk \
  --package com.example.app \
  --install-flag=-d
```

Common flags:

- `-d`: allow version downgrade
- `-g`: grant all runtime permissions declared in the manifest
- `-t`: allow test APKs

## Reading the result

Start with the Markdown report. The **Health findings** section highlights
obvious issues such as low battery, high temperature, full storage, thermal
pressure, or incomplete boot state. The JSON report contains the raw captured
signals for deeper comparison.
