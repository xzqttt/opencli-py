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
extension_connected = False
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
    global extension_ws, extension_connected, pending_requests

    # Reject all pending requests
    for fut in pending_requests.values():
        if not fut.done():
            fut.set_exception(Exception("Daemon shutting down"))
    pending_requests.clear()

    # Close extension WebSocket
    if extension_ws:
        try:
            await extension_ws.close()
        except:
            pass
        extension_ws = None
        extension_connected = False

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
        "extensionConnected": extension_connected,
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

    if not extension_connected or not extension_ws:
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
    global extension_ws, extension_connected

    # Origin check
    origin = request.headers.get("Origin")
    if origin and not origin.startswith("chrome-extension://"):
        return web.Response(status=403)

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    print("[daemon] Extension connected")
    extension_ws = ws
    extension_connected = True
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
            extension_connected = False
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
