import asyncio
import http.client
import importlib
import socket
import subprocess
from contextlib import closing
from urllib.parse import urlsplit

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from confluence_mcp import queue, server, web


def _registered_tool_names(monkeypatch, config_values, value):
    if value is None:
        monkeypatch.delitem(config_values, "CONFLUENCE_ENABLE_WRITES", raising=False)
    else:
        monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", value)
    module = importlib.reload(server)
    return {tool.name for tool in asyncio.run(module.mcp.list_tools())}


def test_write_tools_are_hidden_by_default(monkeypatch, config_values):
    names = _registered_tool_names(monkeypatch, config_values, None)

    assert "create_page" not in names
    assert "add_comment" not in names
    assert "list_queued_operations" not in names
    assert {"search_pages", "get_page", "cql_search"} <= names


def test_write_tools_appear_when_enabled(monkeypatch, config_values):
    names = _registered_tool_names(monkeypatch, config_values, "true")

    assert {
        "create_page",
        "add_comment",
        "update_page",
        "update_page_section",
        "move_page",
        "list_queued_operations",
        "get_queued_operations",
        "cancel_queued_operations",
        "get_execution_log",
    } <= names
    assert "apply_approved_operations" not in names


def test_markdown_page_tools_expose_image_directory_and_queue_through_mcp(fake_client, image_file, config_values):
    from mcp.server.fastmcp import FastMCP

    config_values["CONFLUENCE_ENABLE_WRITES"] = "true"
    mcp = FastMCP("test-images")
    server.register_write_tools(mcp)
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    for name in ("create_page", "update_page", "update_page_section"):
        assert "image_base_dir" in tools[name].inputSchema["properties"]
        assert "image_base_dir" not in tools[name].inputSchema["required"]
    asyncio.run(mcp.call_tool("create_page", {
        "space_key": "OPS", "title": "Images", "content_markdown": f"![图]({image_file.name})",
        "image_base_dir": str(image_file.parent), "dry_run": False,
    }))
    [op] = queue.list_ops()
    assert op["status"] == "pending" and len(queue.get_attachments(op["id"])) == 1
    assert fake_client.uploaded == fake_client.created == []


@pytest.fixture
def review_mcp(monkeypatch, config_values, fake_client):
    config_values.update(CONFLUENCE_ENABLE_WRITES="true", ALLOW_AGENT_OPEN_REVIEW_UI="true")
    module = importlib.reload(server)
    monkeypatch.setattr(module, "get_client", lambda: fake_client)
    yield module.mcp
    module._review_page.close()


def test_open_review_page_reuses_listener_without_exposing_session(
    review_mcp, monkeypatch, fake_client, capfd
):
    opened_urls = []

    def open_browser(command, *, input, stdout, stderr, text, check, timeout):
        assert stdout == stderr == subprocess.DEVNULL
        assert input not in command and text and check
        url = urlsplit(input)
        assert url.hostname == "127.0.0.1"
        with closing(http.client.HTTPConnection(url.hostname, url.port, timeout=5)) as conn:
            conn.request("GET", f"{url.path}?{url.query}")
            response = conn.getresponse()
            assert response.status == 302
            assert web.COOKIE in response.headers["Set-Cookie"]
        opened_urls.append(input)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(web.subprocess, "run", open_browser)
    op_id = queue.enqueue(
        "create_page", kind="create", page_id=None, space_key="OPS", version_before=None,
        summary="Guide", preview="preview", payload={"title": "Guide"},
    )

    async def open_twice():
        return await asyncio.gather(
            review_mcp.call_tool("open_review_page", {}),
            review_mcp.call_tool("open_review_page", {}),
        )

    result = asyncio.run(open_twice())
    first, second = opened_urls
    assert first == second
    token = urlsplit(first).query.removeprefix("token=")
    captured = capfd.readouterr()
    assert "Opened" in str(result)
    assert token and token not in str(result) + captured.out + captured.err
    assert captured.out == ""
    assert queue.get_op(op_id)["status"] == "pending"
    assert fake_client.created == []


def test_open_review_page_releases_listener_if_browser_times_out(review_mcp, monkeypatch):
    opened_urls = []

    def timeout_browser(command, *, input, timeout, **kwargs):
        opened_urls.append(input)
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(web.subprocess, "run", timeout_browser)
    with pytest.raises(ToolError, match="Could not open the default browser") as caught:
        asyncio.run(review_mcp.call_tool("open_review_page", {}))

    [opened] = opened_urls
    url = urlsplit(opened)
    assert url.query not in str(caught.value)
    with pytest.raises(OSError):
        socket.create_connection((url.hostname, url.port), timeout=1).close()
