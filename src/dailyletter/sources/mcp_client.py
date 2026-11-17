"""A small client for MCP servers over Streamable HTTP, enough to call read-only tools.

Used for your own MCP servers (Garmin, later Saxo) that run on the same machine.
Speaks JSON-RPC over POST, accepts both plain JSON and server-sent-event replies,
and sends the access token only as an Authorization header, never in the URL.
"""

from __future__ import annotations

import itertools
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "dailyletter", "version": "0.1"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class McpError(RuntimeError):
    """The server could not be reached or answered with a protocol error."""


class McpToolError(RuntimeError):
    """The tool ran but reported an error, for example an expired Garmin key."""


def check_url(url: str) -> str:
    """HTTPS everywhere; plain HTTP only to this machine, where nothing travels over a network."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return url
    if parts.scheme == "http" and parts.hostname in LOCAL_HOSTS:
        return url
    raise ValueError("Het MCP-adres moet https:// zijn, of http:// naar 127.0.0.1 of localhost.")


def _messages(response: httpx.Response) -> list[dict]:
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/event-stream"):
        messages, data = [], []
        for line in response.text.splitlines():
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line.strip() and data:
                messages.append(json.loads("\n".join(data)))
                data = []
        if data:
            messages.append(json.loads("\n".join(data)))
        return messages
    if not response.content:
        return []
    body = response.json()
    return body if isinstance(body, list) else [body]


class McpClient:
    def __init__(self, url: str, token: str, timeout: float = 30.0, transport: httpx.BaseTransport | None = None):
        self.url = check_url(url)
        # A server on this machine is reached directly, never through a proxy from the environment.
        local = urlsplit(self.url).hostname in LOCAL_HOSTS
        self._http = httpx.Client(timeout=timeout, transport=transport, trust_env=not local)
        self._token = token
        self._ids = itertools.count(1)
        self._session: str | None = None
        self._protocol = PROTOCOL_VERSION

    # -- plumbing -----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
            headers["MCP-Protocol-Version"] = self._protocol
        return headers

    def _post(self, message: dict) -> httpx.Response:
        try:
            response = self._http.post(self.url, json=message, headers=self._headers())
        except httpx.HTTPError as exc:
            raise McpError(f"MCP-server niet bereikbaar ({type(exc).__name__})") from None
        if response.status_code == 401:
            raise McpError("MCP-server weigert het toegangstoken (401)")
        if response.status_code >= 400:
            raise McpError(f"MCP-server gaf HTTP {response.status_code}")
        return response

    def _request(self, method: str, params: dict | None = None) -> Any:
        request_id = next(self._ids)
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        response = self._post(message)
        if method == "initialize":
            self._session = response.headers.get("mcp-session-id")
        for reply in _messages(response):
            if reply.get("id") != request_id:
                continue
            if "error" in reply:
                raise McpError(f"MCP-fout bij {method}: {reply['error'].get('message', 'onbekend')}")
            return reply.get("result")
        raise McpError(f"Geen antwoord van de MCP-server op {method}")

    # -- public -------------------------------------------------------------

    def open(self) -> "McpClient":
        result = self._request(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
        )
        self._protocol = (result or {}).get("protocolVersion", PROTOCOL_VERSION)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def call(self, tool: str, arguments: dict | None = None) -> Any:
        """Call a tool and return its JSON result."""
        result = self._request("tools/call", {"name": tool, "arguments": arguments or {}})
        text = "".join(c.get("text", "") for c in (result or {}).get("content", []) if c.get("type") == "text")
        if (result or {}).get("isError"):
            raise McpToolError(text.splitlines()[0] if text else f"{tool} mislukt")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise McpError(f"{tool} gaf geen JSON terug") from None

    def close(self) -> None:
        if self._session:
            try:
                self._http.delete(self.url, headers=self._headers())
            except httpx.HTTPError:
                pass
        self._http.close()

    def __enter__(self) -> "McpClient":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()
