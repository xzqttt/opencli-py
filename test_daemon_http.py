#!/usr/bin/env python3
"""Test daemon HTTP endpoints without extension."""

import subprocess
import sys
import time
import urllib.request
import json


def main():
    print("=" * 60)
    print("Testing daemon HTTP endpoints")
    print("=" * 60)
    print()

    # Check if port is already in use
    print("1. Checking if port 19826 is available...")
    try:
        req = urllib.request.Request("http://127.0.0.1:19826/ping", timeout=1)
        with urllib.request.urlopen(req):
            print("   ✓ Daemon already running")
            daemon_proc = None
    except Exception:
        print("   Starting daemon...")
        # Start daemon in background
        daemon_proc = subprocess.Popen(
            [sys.executable, "run_daemon.py"],
            cwd="/Users/xiazhiquan/Projects/Github/opencli-py",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        # Wait a bit for daemon to start
        time.sleep(2)

    try:
        # Test /ping
        print("\n2. Testing /ping...")
        req = urllib.request.Request("http://127.0.0.1:19826/ping")
        with urllib.request.urlopen(req, timeout=2) as f:
            data = json.load(f)
            print(f"   ✓ Response: {data}")

        # Test /status (should say extension not connected)
        print("\n3. Testing /status...")
        req = urllib.request.Request(
            "http://127.0.0.1:19826/status",
            headers={"X-OpenCLI": "1"}
        )
        with urllib.request.urlopen(req, timeout=2) as f:
            data = json.load(f)
            print(f"   ✓ Response: {data}")
            print(f"   ✓ extensionConnected: {data.get('extensionConnected')}")

        print("\n" + "=" * 60)
        print("✅ All HTTP endpoints working correctly!")
        print("=" * 60)
        print("\nNow you need to:")
        print("1. Load the extension in Chrome")
        print("2. Refresh the extension")
        print("3. Run python test_debug.py")

    finally:
        if daemon_proc:
            print("\nStopping daemon...")
            daemon_proc.terminate()
            try:
                daemon_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                daemon_proc.kill()


if __name__ == "__main__":
    main()
