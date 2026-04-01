#!/usr/bin/env python3
"""Simple test using the OpenCLI API directly."""

from opencli_py import OpenCLI
import time


def main():
    print("=" * 60)
    print("测试 OpenCLI API")
    print("=" * 60)
    print()

    # We'll manually check daemon first, not use auto-start
    # Because daemon is already running
    import urllib.request
    import json

    print("检查 daemon...")
    try:
        req = urllib.request.Request("http://127.0.0.1:19826/status", headers={"X-OpenCLI": "1"})
        with urllib.request.urlopen(req, timeout=2) as f:
            data = json.load(f)
            print(f"状态: {data}")
    except Exception as e:
        print(f"检查失败: {e}")
        return

    print()
    print("现在直接发送命令到 daemon...")
    print()

    # Send a command manually
    cmd_id = f"cmd_{int(time.time() * 1000)}"
    cmd = {
        "id": cmd_id,
        "action": "navigate",
        "workspace": "default",
        "url": "https://example.com"
    }

    print(f"发送命令: {cmd}")
    print()

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
            print(f"结果: {result}")
    except Exception as e:
        print(f"错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
