"""Protocol definitions for opencli-py."""

from dataclasses import dataclass
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
