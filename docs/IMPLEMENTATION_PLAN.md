# opencli-py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal Python implementation of opencli with goto, evaluate, and cookies functionality, including a Python daemon and Chrome Extension.

**Architecture:** Python client (sync API) → Python daemon (aiohttp HTTP/WebSocket) → Chrome Extension (minimal background service worker)

**Tech Stack:** Python 3.12.8, aiohttp, Chrome Manifest V3 Extension

---

## File Structure

```
opencli-py/
├── pyproject.toml                    # Project metadata and dependencies
├── README.md                         # Usage documentation
├── opencli_py/
│   ├── __init__.py                   # Public API exports
│   ├── protocol.py                   # Command/Result dataclasses
│   ├── daemon.py                     # aiohttp HTTP + WebSocket server
│   └── client.py                     # Sync API wrapper (OpenCLI, Page)
└── opencli_py/extension/
    ├── manifest.json                 # Extension manifest
    └── background.js                 # Extension background service worker
```

---

## Task 1: Project Setup - pyproject.toml

**Files:**
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/pyproject.toml`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "opencli-py"
version = "0.1.0"
description = "Minimal Python browser automation using Chrome Extension"
requires-python = ">=3.12"
authors = [
    { name = "Your Name" }
]
dependencies = [
    "aiohttp>=3.9.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Initialize git repository**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
git init
git add pyproject.toml
git commit -m "chore: initial project setup with pyproject.toml"
```

---

## Task 2: Protocol Definitions

**Files:**
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/opencli_py/protocol.py`
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/opencli_py/__init__.py`

- [ ] **Step 1: Create protocol.py**

```python
"""Protocol definitions for opencli-py."""

from dataclasses import dataclass, field
from typing import Literal, Optional, Any
import json
import time

# Constants
DEFAULT_DAEMON_PORT = 19825
DEFAULT_DAEMON_HOST = "127.0.0.1"
DAEMON_WS_URL = f"ws://{DEFAULT_DAEMON_HOST}:{DEFAULT_DAEMON_PORT}/ext"
DAEMON_PING_URL = f"http://{DEFAULT_DAEMON_HOST}:{DEFAULT_DAEMON_PORT}/ping"
IDLE_TIMEOUT = 5 * 60 * 1000  # 5 minutes

Action = Literal["exec", "navigate", "cookies"]


@dataclass
class Command:
    """Command sent from client to extension."""
    id: str
    action: Action
    workspace: str = "default"
    tabId: Optional[int] = None
    code: Optional[str] = None      # for exec
    url: Optional[str] = None       # for navigate
    domain: Optional[str] = None    # for cookies

    def to_dict(self) -> dict:
        result = {"id": self.id, "action": self.action, "workspace": self.workspace}
        if self.tabId is not None:
            result["tabId"] = self.tabId
        if self.code is not None:
            result["code"] = self.code
        if self.url is not None:
            result["url"] = self.url
        if self.domain is not None:
            result["domain"] = self.domain
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class Result:
    """Result sent from extension to client."""
    id: str
    ok: bool
    data: Optional[Any] = None
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Result":
        return cls(
            id=d.get("id", ""),
            ok=d.get("ok", False),
            data=d.get("data"),
            error=d.get("error")
        )

    @classmethod
    def from_json(cls, s: str) -> "Result":
        return cls.from_dict(json.loads(s))


def generate_id() -> str:
    """Generate a unique command ID."""
    return f"cmd_{int(time.time() * 1000)}_{id(object())}"
```

- [ ] **Step 2: Create __init__.py**

```python
"""opencli-py: Minimal Python browser automation."""

from .client import OpenCLI, Page

__all__ = ["OpenCLI", "Page"]
__version__ = "0.1.0"
```

- [ ] **Step 3: Commit**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
mkdir -p opencli_py
git add opencli_py/protocol.py opencli_py/__init__.py
git commit -m "feat: add protocol definitions"
```

---

## Task 3: Python Daemon (aiohttp)

**Files:**
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/opencli_py/daemon.py`

- [ ] **Step 1: Create daemon.py**

```python
"""HTTP + WebSocket daemon for opencli-py."""

import asyncio
import json
from typing import Optional
from aiohttp import web, WSMessage

from .protocol import (
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_PORT,
    IDLE_TIMEOUT,
    Result,
)

# Global state
extension_ws: Optional[web.WebSocketResponse] = None
pending_requests: dict[str, asyncio.Future] = {}
idle_timer: Optional[asyncio.Task] = None


def reset_idle_timer(app: web.Application):
    """Reset the idle timeout timer."""
    global idle_timer
    if idle_timer and not idle_timer.done():
        idle_timer.cancel()

    async def idle_shutdown():
        await asyncio.sleep(IDLE_TIMEOUT / 1000)
        print("[daemon] Idle timeout, shutting down")
        asyncio.create_task(shutdown(app))

    idle_timer = asyncio.create_task(idle_shutdown())


async def shutdown(app: web.Application):
    """Gracefully shutdown the daemon."""
    global extension_ws, pending_requests

    # Reject all pending requests
    for fut in pending_requests.values():
        if not fut.done():
            fut.set_exception(Exception("Daemon shutting down"))
    pending_requests.clear()

    # Close extension WebSocket
    if extension_ws and not extension_ws.closed:
        await extension_ws.close()
        extension_ws = None

    # Stop the server
    runner = app.get("runner")
    if runner:
        await runner.cleanup()


async def handle_ping(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({"ok": True})


async def handle_status(request: web.Request) -> web.Response:
    """Return daemon status."""
    # Verify X-OpenCLI header
    if "X-OpenCLI" not in request.headers:
        return web.json_response({"ok": False, "error": "Forbidden"}, status=403)

    return web.json_response({
        "ok": True,
        "extensionConnected": extension_ws is not None and not extension_ws.closed,
        "extensionVersion": "0.1.0"
    })


async def handle_command(request: web.Request) -> web.Response:
    """Handle command from client."""
    # Verify X-OpenCLI header
    if "X-OpenCLI" not in request.headers:
        return web.json_response({"ok": False, "error": "Forbidden"}, status=403)

    reset_idle_timer(request.app)

    body = await request.json()
    cmd_id = body.get("id")
    if not cmd_id:
        return web.json_response({"ok": False, "error": "Missing command id"}, status=400)

    if not extension_ws or extension_ws.closed:
        return web.json_response({
            "id": cmd_id,
            "ok": False,
            "error": "Extension not connected"
        }, status=503)

    # Create a future for this request
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    pending_requests[cmd_id] = fut

    try:
        # Forward command to extension
        await extension_ws.send_json(body)

        # Wait for result with timeout
        result = await asyncio.wait_for(fut, timeout=120.0)
        return web.json_response(result)
    except asyncio.TimeoutError:
        return web.json_response({
            "id": cmd_id,
            "ok": False,
            "error": "Command timeout"
        }, status=408)
    finally:
        pending_requests.pop(cmd_id, None)


async def handle_extension_ws(request: web.Request) -> web.WebSocketResponse:
    """Handle WebSocket connection from extension."""
    global extension_ws

    # Origin check
    origin = request.headers.get("Origin")
    if origin and not origin.startswith("chrome-extension://"):
        return web.Response(status=403)

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    print("[daemon] Extension connected")
    extension_ws = ws
    reset_idle_timer(request.app)

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)

                # Handle hello from extension
                if data.get("type") == "hello":
                    continue

                # Handle log messages
                if data.get("type") == "log":
                    level = data.get("level", "info")
                    msg_text = data.get("msg", "")
                    print(f"[ext] [{level}] {msg_text}")
                    continue

                # Handle command result
                msg_id = data.get("id")
                if msg_id and msg_id in pending_requests:
                    fut = pending_requests[msg_id]
                    if not fut.done():
                        fut.set_result(data)

            elif msg.type == web.WSMsgType.ERROR:
                print(f"[daemon] WebSocket error: {ws.exception()}")

    finally:
        print("[daemon] Extension disconnected")
        if extension_ws == ws:
            extension_ws = None
            # Reject pending requests
            for msg_id, fut in list(pending_requests.items()):
                if not fut.done():
                    fut.set_exception(Exception("Extension disconnected"))
            pending_requests.clear()

    return ws


async def run_daemon(host: str = DEFAULT_DAEMON_HOST, port: int = DEFAULT_DAEMON_PORT):
    """Run the daemon."""
    app = web.Application()

    # Routes
    app.router.add_get("/ping", handle_ping)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/command", handle_command)
    app.router.add_get("/ext", handle_extension_ws)

    runner = web.AppRunner(app)
    await runner.setup()
    app["runner"] = runner

    site = web.TCPSite(runner, host, port)
    await site.start()

    reset_idle_timer(app)
    print(f"[daemon] Listening on http://{host}:{port}")

    # Run forever
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        await shutdown(app)


if __name__ == "__main__":
    asyncio.run(run_daemon())
```

- [ ] **Step 2: Commit**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
git add opencli_py/daemon.py
git commit -m "feat: add Python daemon with aiohttp"
```

---

## Task 4: Client API (OpenCLI, Page)

**Files:**
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/opencli_py/client.py`

- [ ] **Step 1: Create client.py**

```python
"""Synchronous client API for opencli-py."""

import asyncio
import json
import threading
import time
from typing import Any, Optional
import urllib.request

from .protocol import (
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_PORT,
    Command,
    Result,
    generate_id,
)


class DaemonNotRunningError(Exception):
    """Raised when daemon is not running."""
    pass


class DaemonThread(threading.Thread):
    """Thread that runs the daemon in background."""

    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self._stop_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def run(self):
        # Import here to avoid circular imports
        from .daemon import run_daemon

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            # Create a task that can be cancelled
            task = self._loop.create_task(run_daemon(self.host, self.port))
            self._loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            self._loop.close()

    def stop(self):
        """Stop the daemon thread."""
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: [t.cancel() for t in asyncio.all_tasks(self._loop)])


class Page:
    """Page API for browser automation."""

    def __init__(self, client: "OpenCLI", workspace: str = "default"):
        self._client = client
        self._workspace = workspace
        self._tab_id: Optional[int] = None
        self._last_url: Optional[str] = None

    def goto(self, url: str) -> None:
        """Navigate to the specified URL."""
        cmd = Command(
            id=generate_id(),
            action="navigate",
            workspace=self._workspace,
            tabId=self._tab_id,
            url=url
        )
        result = self._client._send_command(cmd)
        if not result.ok:
            raise Exception(result.error or "Navigate failed")

        # Remember tabId and URL
        if result.data and isinstance(result.data, dict):
            self._tab_id = result.data.get("tabId")
        self._last_url = url

    def evaluate(self, js: str) -> Any:
        """Execute JavaScript and return the result."""
        # Wrap for eval - ensure it's an IIFE if needed
        wrapped = f"({js})()" if js.strip().startswith(("(", "async")) else js

        cmd = Command(
            id=generate_id(),
            action="exec",
            workspace=self._workspace,
            tabId=self._tab_id,
            code=wrapped
        )
        result = self._client._send_command(cmd)
        if not result.ok:
            raise Exception(result.error or "Evaluate failed")
        return result.data

    def cookies(self, domain: Optional[str] = None, url: Optional[str] = None) -> list[dict]:
        """Get cookies for the domain or URL."""
        if domain is None and url is None:
            raise ValueError("Either domain or url must be provided")

        cmd = Command(
            id=generate_id(),
            action="cookies",
            workspace=self._workspace,
            tabId=self._tab_id,
            domain=domain
        )
        result = self._client._send_command(cmd)
        if not result.ok:
            raise Exception(result.error or "Get cookies failed")

        cookies = result.data
        return cookies if isinstance(cookies, list) else []


class OpenCLI:
    """Main OpenCLI client class."""

    def __init__(self, host: str = DEFAULT_DAEMON_HOST, port: int = DEFAULT_DAEMON_PORT):
        self.host = host
        self.port = port
        self._daemon_thread: Optional[DaemonThread] = None
        self._base_url = f"http://{host}:{port}"

    def start(self) -> None:
        """Start the daemon in background."""
        if self._daemon_thread and self._daemon_thread.is_alive():
            return

        # Check if already running
        if self._is_daemon_running():
            return

        # Start daemon in thread
        self._daemon_thread = DaemonThread(self.host, self.port)
        self._daemon_thread.start()

        # Wait for daemon to be ready
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if self._is_daemon_running():
                break
            time.sleep(0.2)
        else:
            raise Exception("Failed to start daemon")

    def stop(self) -> None:
        """Stop the daemon."""
        if self._daemon_thread and self._daemon_thread.is_alive():
            self._daemon_thread.stop()
            self._daemon_thread.join(timeout=2.0)
            self._daemon_thread = None

    def page(self, workspace: str = "default") -> Page:
        """Get a Page object."""
        if not self._is_daemon_running():
            raise DaemonNotRunningError("Daemon not running. Call start() first.")
        return Page(self, workspace)

    def _is_daemon_running(self) -> bool:
        """Check if daemon is running."""
        try:
            req = urllib.request.Request(f"{self._base_url}/ping", timeout=2)
            with urllib.request.urlopen(req):
                return True
        except Exception:
            return False

    def _send_command(self, cmd: Command) -> Result:
        """Send a command to the daemon."""
        url = f"{self._base_url}/command"
        data = cmd.to_json().encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-OpenCLI": "1"
            }
        )

        with urllib.request.urlopen(req, timeout=120) as f:
            response_data = json.load(f)

        return Result.from_dict(response_data)

    def __enter__(self) -> "OpenCLI":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()
```

- [ ] **Step 2: Commit**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
git add opencli_py/client.py
git commit -m "feat: add client API with OpenCLI and Page classes"
```

---

## Task 5: Chrome Extension - manifest.json

**Files:**
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/opencli_py/extension/manifest.json`

- [ ] **Step 1: Create manifest.json**

```json
{
  "manifest_version": 3,
  "name": "OpenCLI-Py",
  "version": "0.1.0",
  "description": "Browser automation bridge for opencli-py",
  "permissions": [
    "debugger",
    "tabs",
    "cookies",
    "alarms"
  ],
  "host_permissions": [
    "<all_urls>"
  ],
  "background": {
    "service_worker": "background.js"
  },
  "icons": {
    "16": "icons/icon-16.png",
    "32": "icons/icon-32.png",
    "48": "icons/icon-48.png",
    "128": "icons/icon-128.png"
  },
  "action": {
    "default_title": "OpenCLI-Py"
  }
}
```

- [ ] **Step 2: Create icons placeholder directory**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
mkdir -p opencli_py/extension/icons
# Create a simple placeholder (we can copy from opencli later)
echo "Placeholder - copy icons from opencli/extension/icons/" > opencli_py/extension/icons/README.txt
```

- [ ] **Step 3: Commit**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
git add opencli_py/extension/manifest.json opencli_py/extension/icons/README.txt
git commit -m "feat: add extension manifest"
```

---

## Task 6: Chrome Extension - background.js

**Files:**
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/opencli_py/extension/background.js`

- [ ] **Step 1: Create background.js**

```javascript
/**
 * OpenCLI-Py Extension - Background Service Worker
 *
 * Minimal implementation: navigate, exec, cookies
 */

const DAEMON_WS_URL = 'ws://127.0.0.1:19825/ext';
const DAEMON_PING_URL = 'http://127.0.0.1:19825/ping';
const WS_RECONNECT_BASE_DELAY = 2000;
const WS_RECONNECT_MAX_DELAY = 60000;
const WINDOW_IDLE_TIMEOUT = 30000;
const BLANK_PAGE = 'data:text/html,<html></html>';

// State
let ws = null;
let reconnectTimer = null;
let reconnectAttempts = 0;

// Automation sessions: workspace -> { windowId, idleTimer, idleDeadlineAt }
const automationSessions = new Map();

// CDP attached tabs: tabId -> true
const attached = new Set();

// === Console log forwarding ===

const _origLog = console.log.bind(console);
const _origWarn = console.warn.bind(console);
const _origError = console.error.bind(console);

function forwardLog(level, args) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  try {
    const msg = args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ');
    ws.send(JSON.stringify({ type: 'log', level, msg, ts: Date.now() }));
  } catch {}
}

console.log = (...args) => { _origLog(...args); forwardLog('info', args); };
console.warn = (...args) => { _origWarn(...args); forwardLog('warn', args); };
console.error = (...args) => { _origError(...args); forwardLog('error', args); };

// === WebSocket connection ===

async function connect() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;

  // Probe daemon first to avoid console noise
  try {
    const res = await fetch(DAEMON_PING_URL, { signal: AbortSignal.timeout(1000) });
    if (!res.ok) return;
  } catch {
    return;
  }

  try {
    ws = new WebSocket(DAEMON_WS_URL);
  } catch {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log('[opencli-py] Connected to daemon');
    reconnectAttempts = 0;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    ws.send(JSON.stringify({ type: 'hello', version: '0.1.0' }));
  };

  ws.onmessage = async (event) => {
    try {
      const command = JSON.parse(event.data);
      const result = await handleCommand(command);
      ws?.send(JSON.stringify(result));
    } catch (err) {
      console.error('[opencli-py] Message handling error:', err);
    }
  };

  ws.onclose = () => {
    console.log('[opencli-py] Disconnected from daemon');
    ws = null;
    scheduleReconnect();
  };

  ws.onerror = () => {
    ws?.close();
  };
}

const MAX_EAGER_ATTEMPTS = 6;

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectAttempts++;
  if (reconnectAttempts > MAX_EAGER_ATTEMPTS) return;
  const delay = Math.min(WS_RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts - 1), WS_RECONNECT_MAX_DELAY);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

// === Automation window management ===

function getWorkspaceKey(workspace) {
  return workspace?.trim() || 'default';
}

function resetWindowIdleTimer(workspace) {
  const session = automationSessions.get(workspace);
  if (!session) return;
  if (session.idleTimer) clearTimeout(session.idleTimer);
  session.idleDeadlineAt = Date.now() + WINDOW_IDLE_TIMEOUT;
  session.idleTimer = setTimeout(async () => {
    const current = automationSessions.get(workspace);
    if (!current) return;
    try {
      await chrome.windows.remove(current.windowId);
      console.log(`[opencli-py] Automation window ${current.windowId} (${workspace}) closed (idle timeout)`);
    } catch {}
    automationSessions.delete(workspace);
  }, WINDOW_IDLE_TIMEOUT);
}

async function getAutomationWindow(workspace) {
  const existing = automationSessions.get(workspace);
  if (existing) {
    try {
      await chrome.windows.get(existing.windowId);
      return existing.windowId;
    } catch {
      automationSessions.delete(workspace);
    }
  }

  const win = await chrome.windows.create({
    url: BLANK_PAGE,
    focused: false,
    width: 1280,
    height: 900,
    type: 'normal',
  });

  const session = {
    windowId: win.id,
    idleTimer: null,
    idleDeadlineAt: Date.now() + WINDOW_IDLE_TIMEOUT,
  };
  automationSessions.set(workspace, session);
  console.log(`[opencli-py] Created automation window ${session.windowId} (${workspace})`);
  resetWindowIdleTimer(workspace);

  await new Promise(resolve => setTimeout(resolve, 200));
  return session.windowId;
}

// Clean up when window is closed
chrome.windows.onRemoved.addListener((windowId) => {
  for (const [workspace, session] of automationSessions.entries()) {
    if (session.windowId === windowId) {
      console.log(`[opencli-py] Automation window closed (${workspace})`);
      if (session.idleTimer) clearTimeout(session.idleTimer);
      automationSessions.delete(workspace);
    }
  }
});

// === CDP helpers ===

function isDebuggableUrl(url) {
  if (!url) return true;
  return url.startsWith('http://') || url.startsWith('https://') || url === BLANK_PAGE;
}

async function ensureAttached(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (!isDebuggableUrl(tab.url)) {
      attached.delete(tabId);
      throw new Error(`Cannot debug tab ${tabId}: URL is ${tab.url ?? 'unknown'}`);
    }
  } catch (e) {
    if (e instanceof Error && e.message.startsWith('Cannot debug tab')) throw e;
    attached.delete(tabId);
    throw new Error(`Tab ${tabId} no longer exists`);
  }

  if (attached.has(tabId)) {
    try {
      await chrome.debugger.sendCommand({ tabId }, 'Runtime.evaluate', {
        expression: '1', returnByValue: true,
      });
      return;
    } catch {
      attached.delete(tabId);
    }
  }

  try {
    await chrome.debugger.attach({ tabId }, '1.3');
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes('Another debugger is already attached')) {
      try { await chrome.debugger.detach({ tabId }); } catch {}
      try {
        await chrome.debugger.attach({ tabId }, '1.3');
      } catch {
        throw new Error(`attach failed: ${msg}`);
      }
    } else {
      throw new Error(`attach failed: ${msg}`);
    }
  }
  attached.add(tabId);

  try {
    await chrome.debugger.sendCommand({ tabId }, 'Runtime.enable');
  } catch {}
}

async function evaluate(tabId, expression) {
  await ensureAttached(tabId);

  const result = await chrome.debugger.sendCommand({ tabId }, 'Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });

  if (result.exceptionDetails) {
    const errMsg = result.exceptionDetails.exception?.description
      || result.exceptionDetails.text
      || 'Eval error';
    throw new Error(errMsg);
  }

  return result.result?.value;
}

// === Command handlers ===

async function resolveTabId(tabId, workspace) {
  if (tabId !== undefined) {
    try {
      const tab = await chrome.tabs.get(tabId);
      const session = automationSessions.get(workspace);
      if (isDebuggableUrl(tab.url) && session && tab.windowId === session.windowId) {
        return tabId;
      }
    } catch {}
  }

  const windowId = await getAutomationWindow(workspace);
  const tabs = await chrome.tabs.query({ windowId });
  const debuggableTab = tabs.find(t => t.id && isDebuggableUrl(t.url));
  if (debuggableTab?.id) return debuggableTab.id;

  const reuseTab = tabs.find(t => t.id);
  if (reuseTab?.id) {
    await chrome.tabs.update(reuseTab.id, { url: BLANK_PAGE });
    await new Promise(resolve => setTimeout(resolve, 300));
    return reuseTab.id;
  }

  const newTab = await chrome.tabs.create({ windowId, url: BLANK_PAGE, active: true });
  if (!newTab.id) throw new Error('Failed to create tab');
  return newTab.id;
}

async function handleNavigate(cmd) {
  const workspace = getWorkspaceKey(cmd.workspace);
  const tabId = await resolveTabId(cmd.tabId, workspace);
  resetWindowIdleTimer(workspace);

  await chrome.tabs.update(tabId, { url: cmd.url });

  // Wait briefly for navigation to start
  await new Promise(resolve => setTimeout(resolve, 500));

  return { id: cmd.id, ok: true, data: { tabId } };
}

async function handleExec(cmd) {
  const workspace = getWorkspaceKey(cmd.workspace);
  const tabId = await resolveTabId(cmd.tabId, workspace);
  resetWindowIdleTimer(workspace);

  const result = await evaluate(tabId, cmd.code);
  return { id: cmd.id, ok: true, data: result };
}

async function handleCookies(cmd) {
  const details = {};
  if (cmd.domain) details.domain = cmd.domain;
  if (cmd.url) details.url = cmd.url;

  const cookies = await chrome.cookies.getAll(details);
  const data = cookies.map(c => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path,
    secure: c.secure,
    httpOnly: c.httpOnly,
    expirationDate: c.expirationDate,
  }));

  return { id: cmd.id, ok: true, data };
}

async function handleCommand(cmd) {
  const workspace = getWorkspaceKey(cmd.workspace);

  try {
    switch (cmd.action) {
      case 'navigate':
        return await handleNavigate(cmd);
      case 'exec':
        return await handleExec(cmd);
      case 'cookies':
        return await handleCookies(cmd);
      default:
        return { id: cmd.id, ok: false, error: `Unknown action: ${cmd.action}` };
    }
  } catch (err) {
    return {
      id: cmd.id,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

// === Lifecycle ===

let initialized = false;

function initialize() {
  if (initialized) return;
  initialized = true;
  chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
  connect();
  console.log('[opencli-py] Extension initialized');
}

chrome.runtime.onInstalled.addListener(() => {
  initialize();
});

chrome.runtime.onStartup.addListener(() => {
  initialize();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepalive') connect();
});

// CDP cleanup
chrome.tabs.onRemoved.addListener((tabId) => {
  attached.delete(tabId);
});

chrome.debugger.onDetach.addListener((source) => {
  if (source.tabId) attached.delete(source.tabId);
});

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (info.url && !isDebuggableUrl(info.url)) {
    if (attached.has(tabId)) {
      try { await chrome.debugger.detach({ tabId }); } catch {}
      attached.delete(tabId);
    }
  }
});
```

- [ ] **Step 2: Commit**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
git add opencli_py/extension/background.js
git commit -m "feat: add extension background service worker"
```

---

## Task 7: README and Examples

**Files:**
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/README.md`
- Create: `/Users/xiazhiquan/Projects/Github/opencli-py/examples/simple.py`

- [ ] **Step 1: Create README.md**

```markdown
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
```

- [ ] **Step 2: Create examples/simple.py**

```python
#!/usr/bin/env python3
"""Simple example for opencli-py."""

from opencli_py import OpenCLI


def main():
    print("opencli-py example")
    print("=" * 40)

    with OpenCLI() as cli:
        page = cli.page()

        print("\n1. Navigating to https://example.com...")
        page.goto("https://example.com")
        print("   ✓ Done")

        print("\n2. Getting page title via JavaScript...")
        title = page.evaluate("document.title")
        print(f"   Title: {title}")

        print("\n3. Getting cookies...")
        cookies = page.cookies(domain="example.com")
        print(f"   Found {len(cookies)} cookies")
        for cookie in cookies:
            print(f"   - {cookie['name']}: {cookie['value']}")

        print("\n" + "=" * 40)
        print("Example complete!")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
mkdir -p examples
chmod +x examples/simple.py
git add README.md examples/simple.py
git commit -m "docs: add README and example"
```

---

## Task 8: Copy Icons from opencli

**Files:**
- Copy icons from `/Users/xiazhiquan/Projects/Github/opencli/extension/icons/`

- [ ] **Step 1: Copy icon files**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
cp /Users/xiazhiquan/Projects/Github/opencli/extension/icons/icon-*.png opencli_py/extension/icons/
rm opencli_py/extension/icons/README.txt
```

- [ ] **Step 2: Commit**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
git add opencli_py/extension/icons/icon-*.png
git commit -m "feat: add extension icons"
```

---

## Task 9: Test the Installation

**Files:**
- Test the setup end-to-end

- [ ] **Step 1: Install in development mode**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
pip install -e .
```

- [ ] **Step 2: Verify import works**

```bash
python3 -c "import opencli_py; print(f'opencli-py v{opencli_py.__version__} imported successfully')"
```

Expected: `opencli-py v0.1.0 imported successfully`

- [ ] **Step 3: Load Extension in Chrome**

1. Open Chrome
2. Go to `chrome://extensions/`
3. Enable "Developer mode"
4. Click "Load unpacked"
5. Select `/Users/xiazhiquan/Projects/Github/opencli-py/opencli_py/extension`

- [ ] **Step 4: Final commit**

```bash
cd /Users/xiazhiquan/Projects/Github/opencli-py
git status
```

---

## Summary

✅ **Project structure created** - pyproject.toml, package layout
✅ **Protocol defined** - Command/Result dataclasses
✅ **Daemon implemented** - aiohttp HTTP/WebSocket server
✅ **Client API** - OpenCLI + Page sync API
✅ **Chrome Extension** - minimal background worker
✅ **Documentation** - README + examples
✅ **Icons** - extension icons

The project is ready to use!
