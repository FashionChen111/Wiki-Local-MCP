import httpx
import pytest

from confluence_mcp import settings_file
from confluence_mcp.client import ConfluenceAPIError, ConfluenceClient, ConfluenceConnectionError, ConfluenceSettings


def _mock_clients(monkeypatch, handler):
    original = httpx.Client
    clients = []

    def new_client(**kwargs):
        client = original(**kwargs, transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", new_client)
    return clients


def test_page_read_recovers_after_two_connect_failures_with_fresh_clients(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("handshake failed", request=request)
        if len(requests) == 2:
            raise httpx.ConnectTimeout("connect timed out", request=request)
        return httpx.Response(200, json={"id": "42"})

    clients = _mock_clients(monkeypatch, handle)
    client = ConfluenceClient(ConfluenceSettings("https://wiki.example/confluence", "example-token", None))
    try:
        assert client.get_page("42")["id"] == "42"
        assert [item.is_closed for item in clients] == [False, True, True]
        assert [request.method for request in requests] == ["GET"] * 3
        assert all(request.url.path == "/confluence/rest/api/content/42" for request in requests)
        assert all(request.headers["Authorization"] == "Bearer example-token" for request in requests)
    finally:
        client.close()


@pytest.mark.parametrize("retries", [0, 1])
def test_read_connect_retry_count_is_loaded_from_dotenv_and_reports_reset(tmp_path, monkeypatch, retries):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ATLASSIAN_CONFLUENCE_URL=https://wiki.example/confluence\n"
        "ATLASSIAN_CONFLUENCE_PAT=example-token\n"
        f"CONFLUENCE_CONNECT_RETRIES={retries}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_file, "get_settings", lambda: settings_file.load_env_file(env_file))
    calls = []

    def reset(request):
        calls.append(request.method)
        raise httpx.ConnectError("TLS handshake failed", request=request) from ConnectionResetError("transport detail")

    clients = _mock_clients(monkeypatch, reset)
    client = ConfluenceClient(ConfluenceSettings.from_environment())
    try:
        with pytest.raises(ConfluenceConnectionError, match="connection was reset.*VPN or zero-trust") as caught:
            client.list_spaces(limit=1, start=0)
        assert "transport detail" not in str(caught.value)
        assert calls == ["GET"] * (retries + 1)
        assert all(item.is_closed for item in clients[1:])
    finally:
        client.close()


@pytest.mark.parametrize(("request_method", "error", "message"), [
    ("GET", httpx.ReadTimeout, "waiting for the Confluence response"),
    ("GET", httpx.PoolTimeout, "connection pool"),
    ("POST", httpx.ConnectError, "Could not connect"),
])
def test_connect_retries_stop_outside_read_connection_setup(monkeypatch, request_method, error, message):
    calls = []

    def fail(request):
        calls.append(request.method)
        raise error("request failed", request=request)

    clients = _mock_clients(monkeypatch, fail)
    client = ConfluenceClient(ConfluenceSettings("https://wiki.example/confluence", "example-token", None))
    try:
        with pytest.raises(ConfluenceAPIError, match=message):
            if request_method == "GET":
                client.search_cql("type = page", limit=5, start=0)
            else:
                client.create_content({"type": "page"})
        assert calls == [request_method] and len(clients) == 1
    finally:
        client.close()
