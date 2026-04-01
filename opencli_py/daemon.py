"""HTTP + WebSocket daemon for opencli-py - zero dependencies!"""

import asyncio
import json
import re
import struct
import base64
import hashlib
from typing import Optional, Dict, Any

from .protocol import (
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_PORT,
    IDLE_TIMEOUT,
)

# Global state
extension_ws: Optional["WebSocketConnection"] = None
pending_requests: Dict[str, asyncio.Future] = {}
idle_timer: Optional[asyncio.Task] = None


def reset_idle_timer():
    """Reset the idle timeout timer."""
    global idle_timer
    if idle_timer and not idle_timer.done():
        idle_timer.cancel()

    async def idle_shutdown():
        await asyncio.sleep(IDLE_TIMEOUT / 1000)
        print("[daemon] Idle timeout, shutting down")
        asyncio.create_task(shutdown())

    idle_timer = asyncio.create_task(idle_shutdown())


async def shutdown():
    """Gracefully shutdown the daemon."""
    global extension_ws, pending_requests

    # Reject all pending requests
    for fut in pending_requests.values():
        if not fut.done():
            fut.set_exception(Exception("Daemon shutting down"))
    pending_requests.clear()

    # Close extension WebSocket
    if extension_ws is not None:
        try:
            await extension_ws.close()
        except:
            pass
        extension_ws = None


class WebSocketConnection:
    """Simple WebSocket connection handler."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.closed = False

    async def send_json(self, data: Any):
        """Send JSON data as text frame."""
        if self.closed:
            return
        payload = json.dumps(data).encode("utf-8")
        await self._send_frame(0x1, payload)

    async def _send_frame(self, opcode: int, payload: bytes):
        """Send a WebSocket frame."""
        frame = bytearray()

        # Fin + Opcode
        frame.append(0x80 | opcode)

        # Length
        length = len(payload)
        if length <= 125:
            frame.append(length)
        elif length <= 65535:
            frame.append(126)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(127)
            frame.extend(struct.pack(">Q", length))

        # Payload
        frame.extend(payload)

        self.writer.write(frame)
        await self.writer.drain()

    async def recv_frame(self):
        """Receive a WebSocket frame."""
        # Read header
        header = await self.reader.readexactly(2)
        fin = (header[0] & 0x80) != 0
        opcode = header[0] & 0x0F
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F

        if length == 126:
            length_bytes = await self.reader.readexactly(2)
            length = struct.unpack(">H", length_bytes)[0]
        elif length == 127:
            length_bytes = await self.reader.readexactly(8)
            length = struct.unpack(">Q", length_bytes)[0]

        # Read mask key if masked
        mask_key = b""
        if masked:
            mask_key = await self.reader.readexactly(4)

        # Read payload
        payload = await self.reader.readexactly(length)

        # Unmask if needed
        if masked and mask_key:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        return fin, opcode, payload

    async def close(self):
        """Close the WebSocket connection."""
        if self.closed:
            return
        self.closed = True
        try:
            # Send close frame
            await self._send_frame(0x8, b"")
            self.writer.close()
            await self.writer.wait_closed()
        except:
            pass


async def handle_http_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single HTTP request."""
    global extension_ws

    # Read request line
    request_line = await reader.readline()
    if not request_line:
        return

    request_line = request_line.decode("utf-8").strip()
    if not request_line:
        return

    # Parse request line
    match = re.match(r"^(\S+)\s+(\S+)\s+HTTP/(\d+\.\d+)", request_line)
    if not match:
        await send_http_response(writer, 400, "Bad Request")
        return

    method, path, version = match.groups()

    # Read headers
    headers = {}
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        line = line.decode("utf-8").strip()
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    # Check for WebSocket upgrade
    upgrade = headers.get("Upgrade", "").lower()
    connection = headers.get("Connection", "").lower()
    if "upgrade" in connection and "websocket" in upgrade:
        await handle_websocket_upgrade(reader, writer, headers, headers.get("Sec-WebSocket-Key"))
        return

    # Route HTTP requests
    if method == "GET" and path == "/ping":
        await handle_ping(writer)
    elif method == "GET" and path == "/status":
        await handle_status(writer, headers)
    elif method == "POST" and path == "/command":
        # Read body
        content_length = int(headers.get("Content-Length", 0))
        body = await reader.readexactly(content_length) if content_length > 0 else b""
        await handle_command(writer, headers, body)
    else:
        await send_http_response(writer, 404, "Not Found")


async def handle_websocket_upgrade(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, headers: dict, ws_key: str):
    """Handle WebSocket upgrade request."""
    global extension_ws

    # Origin check
    origin = headers.get("Origin", "")
    if origin and not origin.startswith("chrome-extension://"):
        await send_http_response(writer, 403, "Forbidden")
        return

    # Generate accept key
    accept_key = ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept_hash = hashlib.sha1(accept_key.encode("utf-8")).digest()
    accept = base64.b64encode(accept_hash).decode("utf-8")

    # Send handshake response
    response_lines = [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Accept: {accept}",
        "",
        "",
    ]
    response = "\r\n".join(response_lines).encode("utf-8")
    writer.write(response)
    await writer.drain()

    ws = WebSocketConnection(reader, writer)

    print("[daemon] Extension connected")
    extension_ws = ws
    reset_idle_timer()

    try:
        while not ws.closed:
            try:
                fin, opcode, payload = await ws.recv_frame()

                # Close frame
                if opcode == 0x8:
                    break

                # Ping frame
                if opcode == 0x9:
                    await ws._send_frame(0xA, payload)
                    continue

                # Text frame
                if opcode == 0x1:
                    data = json.loads(payload.decode("utf-8"))

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

            except asyncio.IncompleteReadError:
                break
            except Exception as e:
                if not ws.closed:
                    print(f"[daemon] WebSocket error: {e}")
                break

    finally:
        print("[daemon] Extension disconnected")
        if extension_ws == ws:
            extension_ws = None
            # Reject pending requests
            for msg_id, fut in list(pending_requests.items()):
                if not fut.done():
                    fut.set_exception(Exception("Extension disconnected"))
            pending_requests.clear()
        await ws.close()


def json_response(data: Any, status: int = 200) -> bytes:
    """Create JSON HTTP response."""
    body = json.dumps(data).encode("utf-8")
    return (
        f"HTTP/1.1 {status} OK\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    ).encode("utf-8") + body


async def send_http_response(writer: asyncio.StreamWriter, status: int, message: str):
    """Send a simple HTTP response."""
    response = (
        f"HTTP/1.1 {status} {message}\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    ).encode("utf-8")
    writer.write(response)
    await writer.drain()


async def handle_ping(writer: asyncio.StreamWriter):
    """Health check endpoint."""
    response = json_response({"ok": True})
    writer.write(response)
    await writer.drain()


async def handle_status(writer: asyncio.StreamWriter, headers: dict):
    """Return daemon status."""
    # Verify X-OpenCLI header
    if "X-OpenCLI" not in headers:
        response = json_response({"ok": False, "error": "Forbidden"}, status=403)
        writer.write(response)
        await writer.drain()
        return

    print(f"[daemon] handle_status: extension_ws={extension_ws}, id={id(extension_ws) if extension_ws is not None else 'None'}")

    response = json_response({
        "ok": True,
        "extensionConnected": extension_ws is not None,
        "extensionVersion": "0.1.0"
    })
    writer.write(response)
    await writer.drain()


async def handle_command(writer: asyncio.StreamWriter, headers: dict, body: bytes):
    """Handle command from client."""
    global extension_ws

    # Verify X-OpenCLI header
    if "X-OpenCLI" not in headers:
        response = json_response({"ok": False, "error": "Forbidden"}, status=403)
        writer.write(response)
        await writer.drain()
        return

    reset_idle_timer()

    try:
        cmd_data = json.loads(body.decode("utf-8"))
    except:
        response = json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        writer.write(response)
        await writer.drain()
        return

    cmd_id = cmd_data.get("id")
    if not cmd_id:
        response = json_response({"ok": False, "error": "Missing command id"}, status=400)
        writer.write(response)
        await writer.drain()
        return

    print(f"[daemon] handle_command: extension_ws={extension_ws}, is None={extension_ws is None}")

    if extension_ws is None:
        print(f"[daemon] handle_command: returning 503!")
        response = json_response({
            "id": cmd_id,
            "ok": False,
            "error": "Extension not connected"
        }, status=503)
        writer.write(response)
        await writer.drain()
        return

    # Create a future for this request
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    pending_requests[cmd_id] = fut

    try:
        # Forward command to extension
        await extension_ws.send_json(cmd_data)

        # Wait for result with timeout
        result = await asyncio.wait_for(fut, timeout=120.0)
        response = json_response(result)
        writer.write(response)
        await writer.drain()
    except asyncio.TimeoutError:
        response = json_response({
            "id": cmd_id,
            "ok": False,
            "error": "Command timeout"
        }, status=408)
        writer.write(response)
        await writer.drain()
    finally:
        pending_requests.pop(cmd_id, None)


async def run_daemon(host: str = DEFAULT_DAEMON_HOST, port: int = DEFAULT_DAEMON_PORT):
    """Run the daemon."""

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            await handle_http_request(reader, writer)
        except Exception as e:
            print(f"[daemon] Client error: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass

    server = await asyncio.start_server(
        handle_client, host, port)

    reset_idle_timer()
    print(f"[daemon] Listening on http://{host}:{port}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(run_daemon())
