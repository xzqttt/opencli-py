#!/usr/bin/env python3
"""Test script to fetch Baidu news hot topics."""

import time
import urllib.request
import json


def send_command(cmd):
    """Send a command to the daemon."""
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

    with urllib.request.urlopen(req, timeout=120) as f:
        return json.load(f)


def main():
    print("=" * 60)
    print("opencli-py - 百度新闻测试")
    print("=" * 60)
    print()

    print("请确保：")
    print("1. Daemon 已在运行 (python run_daemon.py)")
    print("2. Extension 已在 Chrome 中加载")
    print()

    input("按回车继续...")

    # Generate a command ID
    import time
    cmd_id = f"cmd_{int(time.time() * 1000)}"

    # Step 1: Navigate to Baidu News
    print("\n1. 导航到百度新闻...")
    cmd = {
        "id": cmd_id + "_1",
        "action": "navigate",
        "workspace": "default",
        "url": "https://news.baidu.com/"
    }
    result = send_command(cmd)
    if not result.get("ok"):
        print(f"❌ 失败: {result.get('error')}")
        return
    print("✅ 成功")
    tab_id = result.get("data", {}).get("tabId")
    print(f"   Tab ID: {tab_id}")

    # Wait a bit
    time.sleep(3)

    # Step 2: Get hot news
    print("\n2. 获取热点要闻...")
    cmd_id = f"cmd_{int(time.time() * 1000)}"

    # JavaScript to extract hot news
    js_code = """
    (function() {
        var results = [];
        // Try to find hot news elements
        var selectors = [
            '.hotnews a',
            '.hot-news a',
            '[class*="hot"] a',
            'a[href*="hot"]',
            'li a'
        ];
        for (var s of selectors) {
            var elements = document.querySelectorAll(s);
            for (var el of elements) {
                var text = el.textContent.trim();
                var href = el.href;
                if (text && href && text.length > 5) {
                    results.push({
                        title: text.substring(0, 100),
                        url: href
                    });
                }
            }
            if (results.length >= 10) break;
        }
        return results.slice(0, 10);
    })()
    """

    cmd = {
        "id": cmd_id + "_2",
        "action": "exec",
        "workspace": "default",
        "tabId": tab_id,
        "code": js_code
    }
    result = send_command(cmd)
    if not result.get("ok"):
        print(f"❌ 失败: {result.get('error')}")
        return

    news = result.get("data", [])
    print(f"✅ 成功获取 {len(news)} 条新闻")
    print()

    for i, item in enumerate(news, 1):
        print(f"{i:2d}. {item.get('title', 'N/A')}")
        print(f"    {item.get('url', '')}")
        print()

    print("=" * 60)
    print("完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
