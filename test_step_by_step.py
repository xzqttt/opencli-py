#!/usr/bin/env python3
"""Step by step test for opencli-py."""

import time
import urllib.request
import json


def check_daemon():
    """Check if daemon is running."""
    try:
        req = urllib.request.Request("http://127.0.0.1:19826/ping")
        with urllib.request.urlopen(req, timeout=2) as f:
            print("✅ Daemon is running!")
            return True
    except Exception as e:
        print(f"❌ Daemon not running: {e}")
        return False


def check_extension():
    """Check if extension is connected."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:19826/status",
            headers={"X-OpenCLI": "1"}
        )
        with urllib.request.urlopen(req, timeout=2) as f:
            data = json.load(f)
            if data.get("extensionConnected"):
                print("✅ Extension is connected!")
                return True
            else:
                print("❌ Extension NOT connected!")
                print("   Please load the extension in Chrome:")
                print("   1. Open chrome://extensions/")
                print("   2. Enable Developer mode")
                print("   3. Click 'Load unpacked'")
                print(f"   4. Select: /Users/xiazhiquan/Projects/Github/opencli-py/opencli_py/extension")
                return False
    except Exception as e:
        print(f"❌ Status check failed: {e}")
        return False


def main():
    print("=" * 60)
    print("opencli-py 测试")
    print("=" * 60)
    print()

    print("步骤 1: 检查 daemon...")
    if not check_daemon():
        print("\n请先在另一个终端运行:")
        print("  cd /Users/xiazhiquan/Projects/Github/opencli-py")
        print("  python run_daemon.py")
        return

    print()
    print("步骤 2: 检查 extension...")
    if not check_extension():
        return

    print()
    print("=" * 60)
    print("✅ 所有检查通过！现在可以运行 examples/simple.py 了")
    print("=" * 60)


if __name__ == "__main__":
    main()
