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

        # Wait for daemon to be ready - longer wait and more forgiving
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if self._is_daemon_running():
                break
            time.sleep(0.5)
        else:
            # Even if ping fails, daemon might still be starting up - give it a bit more time
            time.sleep(2.0)

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
