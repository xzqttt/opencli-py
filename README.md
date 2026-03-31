# opencli-py

Minimal Python browser automation using Chrome Extension.

## Features

- **goto(url)** - Navigate to a URL
- **evaluate(js)** - Execute JavaScript in the page
- **cookies(domain/url)** - Get cookies from the browser
- **Silent** - Runs in an independent Chrome window, doesn't interfere with your browsing
- **Reuse login state** - Uses your existing Chrome cookies and sessions

## Installation

### 1. Install the Python package

```bash
cd opencli-py
pip install -e .
```

### 2. Install the Chrome Extension

1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" (toggle in top right)
3. Click "Load unpacked"
4. Select the `opencli_py/extension` folder

## Quick Start

```python
from opencli_py import OpenCLI

# Start the daemon and get a page
cli = OpenCLI()
cli.start()

page = cli.page()

# Navigate to a website
page.goto("https://example.com")

# Execute JavaScript
title = page.evaluate("document.title")
print(f"Title: {title}")

# Get cookies
cookies = page.cookies(domain="example.com")
print(f"Cookies: {len(cookies)}")

# Stop the daemon
cli.stop()
```

Or using `with` statement (auto-start/stop):

```python
from opencli_py import OpenCLI

with OpenCLI() as cli:
    page = cli.page()
    page.goto("https://example.com")
    title = page.evaluate("document.title")
    print(title)
```

## API Reference

### OpenCLI

```python
OpenCLI(host="127.0.0.1", port=19825)
```

**Methods:**
- `start()` - Start the daemon in background
- `stop()` - Stop the daemon
- `page(workspace="default")` - Get a Page object

### Page

```python
page = cli.page()
```

**Methods:**
- `goto(url: str)` - Navigate to the specified URL
- `evaluate(js: str) -> Any` - Execute JavaScript and return the result
- `cookies(domain: str | None = None, url: str | None = None) -> list[dict]` - Get cookies

## How it works

```
Your Python script
    ↓
OpenCLI client (sync API)
    ↓
Python daemon (aiohttp HTTP/WebSocket)
    ↓
Chrome Extension (background service worker)
    ↓
Chrome Debugger Protocol
    ↓
Independent Chrome window (doesn't interfere with your browsing)
```

## License

Apache-2.0
