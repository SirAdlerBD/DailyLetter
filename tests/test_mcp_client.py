import json

import httpx
import pytest

from dailyletter.sources.mcp_client import McpClient, McpError, McpToolError, check_url

TOKEN = "s" * 64


class FakeServer:
    """Answers like the TypeScript MCP SDK: server-sent events, a session id, a bearer token."""

    def __init__(self, tool_result=None, tool_error=None):
        self.seen = []
        self.tool_result = tool_result if tool_result is not None else {"ok": True}
        self.tool_error = tool_error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401)
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        if "id" not in body:
            return httpx.Response(202)
        if body["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "fake"}}
            return self.sse(body["id"], result, headers={"mcp-session-id": "sess-1"})
        assert request.headers["mcp-session-id"] == "sess-1"
        assert request.headers["mcp-protocol-version"] == "2025-03-26"
        if self.tool_error:
            return self.sse(body["id"], {"isError": True, "content": [{"type": "text", "text": self.tool_error}]})
        return self.sse(body["id"], {"content": [{"type": "text", "text": json.dumps(self.tool_result)}]})

    @staticmethod
    def sse(request_id, result, headers=None):
        payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
        return httpx.Response(200, text=f"event: message\ndata: {payload}\n\n",
                              headers={"content-type": "text/event-stream", **(headers or {})})


def client(server, token=TOKEN):
    return McpClient("http://127.0.0.1:3001/mcp", token, transport=httpx.MockTransport(server))


def test_calls_a_tool_and_closes_the_session():
    server = FakeServer(tool_result={"sleep": {"hours": 7.5}})
    with client(server) as mcp:
        assert mcp.call("get_recovery_snapshot", {"date": "2026-11-16"}) == {"sleep": {"hours": 7.5}}
    methods = [r.method for r in server.seen]
    assert methods[-1] == "DELETE"
    assert all("token" not in str(r.url) for r in server.seen)


def test_a_tool_error_is_raised_with_its_first_line():
    server = FakeServer(tool_error="AUTHENTICATION REQUIRED: create a new key\nmore details")
    with client(server) as mcp:
        with pytest.raises(McpToolError, match="^AUTHENTICATION REQUIRED: create a new key$"):
            mcp.call("get_recovery_snapshot")


def test_a_wrong_token_is_reported_without_the_token():
    with pytest.raises(McpError) as caught:
        client(FakeServer(), token="wrong-token-value-1234567890").open()
    assert "401" in str(caught.value) and "wrong-token" not in str(caught.value)


def test_plain_http_only_to_this_machine():
    assert check_url("http://127.0.0.1:3001/mcp")
    assert check_url("http://localhost:3001/mcp")
    assert check_url("https://garmin-mcp-v1.duckdns.org/mcp")
    with pytest.raises(ValueError):
        check_url("http://garmin-mcp-v1.duckdns.org/mcp")
