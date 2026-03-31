# opencli-py 设计规格书

**日期：** 2026-03-31
**版本：** 0.1.0

## 概述

opencli-py 是 opencli 的轻量级 Python 实现，提供浏览器自动化能力，复用用户已登录的 Chrome 状态，且不干扰正常办公。

### 核心原则

- **极简**：只实现最核心的功能
- **静默**：在独立窗口中运行，不干扰用户正常浏览
- **可控**：纯 Python 技术栈，代码完全可控

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                  Python 客户端代码                       │
│  (用户脚本)                                              │
└────────────────────┬────────────────────────────────────┘
                     │ 函数调用
                     ▼
┌─────────────────────────────────────────────────────────┐
│              OpenCLI 类（同步 API）                     │
│  - start() / stop()                                     │
│  - page() 返回 Page 对象                                │
└────────────────────┬────────────────────────────────────┘
                     │ 内部异步调用
                     ▼
┌─────────────────────────────────────────────────────────┐
│         Python Daemon (aiohttp HTTP + WebSocket)       │
│  HTTP: /ping, /status, /command                        │
│  WebSocket: /ext (与 Extension 通信)                   │
└────────────────────┬────────────────────────────────────┘
                     │ WebSocket
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Chrome Extension (极简版)                  │
│  - background service worker                            │
│  - chrome.debugger API                                  │
│  - chrome.cookies API                                   │
└─────────────────────────────────────────────────────────┘
```

## 项目结构

```
opencli-py/
├── README.md
├── pyproject.toml
├── opencli_py/
│   ├── __init__.py          # 公开 API: OpenCLI, Page
│   ├── client.py            # 同步 API 封装
│   ├── daemon.py            # aiohttp HTTP + WebSocket 服务器
│   ├── protocol.py          # 协议定义 (Command, Result)
│   └── extension/           # Chrome Extension 源码
│       ├── manifest.json
│       ├── background.js
│       └── icons/
└── examples/
    └── simple.py            # 使用示例
```

## API 设计

### OpenCLI 类

```python
class OpenCLI:
    def __init__(self, host="127.0.0.1", port=19825):
        """
        创建 OpenCLI 实例

        Args:
            host: daemon 监听地址
            port: daemon 监听端口
        """

    def start(self) -> None:
        """启动 daemon（在后台线程运行）"""

    def stop(self) -> None:
        """停止 daemon"""

    def page(self, workspace: str = "default") -> Page:
        """
        获取 Page 对象

        Args:
            workspace: 工作区名称，用于隔离不同的自动化会话

        Returns:
            Page 对象
        """

    def __enter__(self) -> "OpenCLI":
        """with 语句支持，自动 start"""

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """with 语句支持，自动 stop"""
```

### Page 类

```python
class Page:
    def __init__(self, client, workspace="default"):
        """通常不直接创建，通过 OpenCLI.page() 获取"""

    def goto(self, url: str) -> None:
        """
        导航到指定 URL

        Args:
            url: 目标 URL，必须是 http:// 或 https:// 开头
        """

    def evaluate(self, js: str) -> Any:
        """
        执行 JavaScript 并返回结果

        Args:
            js: JavaScript 代码字符串

        Returns:
            JS 执行结果，自动 JSON 序列化/反序列化
        """

    def cookies(self, domain: str | None = None, url: str | None = None) -> list[dict]:
        """
        获取 cookies

        Args:
            domain: 按域名过滤
            url: 按 URL 过滤

        Returns:
            Cookie 列表，每个 cookie 包含: name, value, domain, path, secure, httpOnly, expirationDate

        Note:
            domain 和 url 至少需要提供一个
        """
```

## 协议设计

### Command（客户端 → Extension）

```python
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class Command:
    id: str
    action: Literal["exec", "navigate", "cookies"]
    workspace: str = "default"
    tabId: Optional[int] = None

    # exec action
    code: Optional[str] = None

    # navigate action
    url: Optional[str] = None

    # cookies action
    domain: Optional[str] = None
```

### Result（Extension → 客户端）

```python
@dataclass
class Result:
    id: str
    ok: bool
    data: Optional[Any] = None
    error: Optional[str] = None
```

### HTTP 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ping` | GET | 健康检查，无 X-OpenCLI 头要求 |
| `/status` | GET | 获取状态，返回 `{extensionConnected, extensionVersion}` |
| `/command` | POST | 发送命令 |

### 安全机制

- **Origin 检查**：拒绝非 `chrome-extension://` 或无 Origin 的请求
- **X-OpenCLI 头**：所有非 ping 请求需要此头
- **loopback-only**：只监听 127.0.0.1

## Extension 设计

### manifest.json

```json
{
  "manifest_version": 3,
  "name": "OpenCLI-Py",
  "version": "0.1.0",
  "description": "Browser automation bridge for opencli-py",
  "permissions": ["debugger", "tabs", "cookies", "alarms"],
  "host_permissions": ["<all_urls>"],
  "background": {
    "service_worker": "background.js"
  }
}
```

### background.js 核心功能

1. **WebSocket 连接管理**
   - 连接到 `ws://127.0.0.1:19825/ext`
   - 自动重连机制
   - Keepalive alarm（每 24 秒）

2. **Command 处理**
   - `navigate`：使用 `chrome.tabs.update`
   - `exec`：使用 `chrome.debugger.sendCommand` + `Runtime.evaluate`
   - `cookies`：使用 `chrome.cookies.getAll`

3. **自动化窗口管理**
   - 创建独立的 Chrome 窗口用于自动化
   - 不干扰用户现有窗口

## Daemon 设计

### 核心组件

1. **HTTP 服务器**（aiohttp）
   - 处理 `/ping`, `/status`, `/command`
   - 安全检查

2. **WebSocket 服务器**（aiohttp）
   - `/ext` 端点用于 Extension 连接
   - 双向消息转发

3. **Idle 超时**
   - 5 分钟无活动自动退出
   - 每次收到命令重置计时器

### 线程模型

- **主线程**：运行用户的同步 API 调用
- **后台线程**：运行 asyncio 事件循环 + aiohttp 服务器

## 使用示例

### 基本使用

```python
from opencli_py import OpenCLI

cli = OpenCLI()
cli.start()

page = cli.page()
page.goto("https://example.com")
title = page.evaluate("document.title")
cookies = page.cookies(domain="example.com")

print(f"Title: {title}")
print(f"Cookies count: {len(cookies)}")

cli.stop()
```

### 使用 with 语句

```python
from opencli_py import OpenCLI

with OpenCLI() as cli:
    page = cli.page()
    page.goto("https://example.com")
    title = page.evaluate("document.title")
    print(title)
```

### 获取登录后的数据

```python
from opencli_py import OpenCLI

with OpenCLI() as cli:
    page = cli.page()

    # 导航到需要登录的网站（复用 Chrome 已登录状态）
    page.goto("https://some-site.com/user/profile")

    # 提取用户数据
    user_data = page.evaluate("""
        (() => {
            return {
                name: document.querySelector('.user-name')?.textContent,
                email: document.querySelector('.user-email')?.textContent
            };
        })()
    """)

    print(user_data)
```

## 技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| Python | CPython | 3.12.8 |
| HTTP/WebSocket | aiohttp | 最新版 |
| Chrome Extension | Manifest V3 | - |

## 依赖项

```toml
[project]
dependencies = [
    "aiohttp>=3.9.0",
]
```

## 安全考虑

1. **仅监听 localhost**：daemon 只绑定 127.0.0.1，不暴露到网络
2. **Origin 检查**：防止 CSRF 攻击
3. **X-OpenCLI 头**：防止浏览器跨域请求
4. **无 CORS**：不发送 Access-Control-Allow-Origin 头

## 未来扩展（可选）

当前版本只实现核心 3 个功能，未来可按需添加：

- `screenshot()` - 截图
- `click()` / `type_text()` - DOM 交互
- `wait()` - 等待元素/文本
- `scroll()` - 滚动页面
- `tabs` 管理 - 新建/关闭标签页
