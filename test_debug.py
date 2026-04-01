#!/usr/bin/env python3
"""Debug test - check status and send command in one script."""

import urllib.request
import json
import time


def check_status():
    """Check daemon status."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:19826/status",
            headers={"X-OpenCLI": "1"}
        )
        with urllib.request.urlopen(req, timeout=2) as f:
            data = json.load(f)
            print(f"[DEBUG] Status: {data}")
            return data
    except Exception as e:
        print(f"[DEBUG] Status check failed: {e}")
        return None


def send_navigate():
    """Send navigate command."""
    cmd_id = f"cmd_{int(time.time() * 1000)}"
    cmd = {
        "id": cmd_id,
        "action": "navigate",
        "workspace": "default",
        "url": "https://example.com"
    }

    print(f"[DEBUG] Sending command: {cmd}")

    url = "http://127.0.0.1:19826/command"
    data = json.dumps(cmd).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-OpenCLI": "1"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as f:
            result = json.load(f)
            print(f"[DEBUG] Result: {result}")
            return result
    except Exception as e:
        print(f"[DEBUG] Error: {type(e).__name__}: {e}")
        return None


def main():
    print("=" * 60)
    print("Debug Test")
    print("=" * 60)
    print()

    # Check status first
    print("1. Checking status...")
    status = check_status()
    if not status:
        print("❌ Status check failed")
        return

    if not status.get("extensionConnected"):
        print("❌ Extension not connected")
        return

    print("✅ Extension is connected")
    print()

    # Wait a bit
    time.sleep(0.5)

    # Check status again
    print("2. Checking status again...")
    status2 = check_status()
    if not status2 or not status2.get("extensionConnected"):
        print("❌ Extension disconnected!")
        return

    print("✅ Extension still connected")
    print()

    # Try to send command
    print("3. Sending navigate command...")
    result = send_navigate()

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
