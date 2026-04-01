#!/usr/bin/env python3
"""Simple test to check daemon ping."""

import urllib.request


def test_ping():
    """Test if daemon responds to ping."""
    try:
        req = urllib.request.Request("http://127.0.0.1:19826/ping", timeout=2)
        with urllib.request.urlopen(req) as f:
            print(f"Ping response: {f.read().decode('utf-8')}")
            return True
    except Exception as e:
        print(f"Ping failed: {e}")
        return False


if __name__ == "__main__":
    test_ping()
