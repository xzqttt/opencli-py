#!/usr/bin/env python3
"""Run daemon manually for testing."""

import asyncio
from opencli_py.daemon import run_daemon


if __name__ == "__main__":
    print("Starting daemon on port 19826...")
    asyncio.run(run_daemon())
