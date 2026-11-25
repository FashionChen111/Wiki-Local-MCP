from unittest.mock import patch

import httpx
import pytest

from confluence_mcp.client import ConfluenceAPIError, ConfluenceClient, ConfluenceConnectionError
from confluence_mcp.client import ConfluenceSettings


class ConflictResponse:
    status_code = 409
    is_redirect = False
    is_error = True


class ConflictHttp:
    def request(self, *args, **kwargs):
        return ConflictResponse()


def _transport_client(handler, settings=None):
    new_client = httpx.Client
    with patch.object(httpx, "Client", side_effect=lambda **kw: new_client(**kw, transport=httpx.MockTransport(handler))):
        return ConfluenceClient(settings or ConfluenceSettings("https://wiki.example/confluence", "example-token", None))


def test_update_conflict_maps_409_to_readable_error():
    client = ConfluenceClient.__new__(ConfluenceClient)
    client._client = ConflictHttp()

    with pytest.raises(ConfluenceAPIError, match="version changed") as excinfo:
        client.update_page("42", {"id": "42"})

    assert excinfo.value.status_code == 409


@pytest.mark.parametrize("status", [200, 204, 403, 202])
def test_trash_page_accepts_only_confirmed_delete_responses(status):
    def handle(request):
        assert request.method == "DELETE" and request.url.path == "/confluence/rest/api/content/42"
        assert not request.url.params
        assert request.headers["authorization"] == "Bearer example-token"
        return httpx.Response(status)

    client = _transport_client(handle)
    try:
        if status in {200, 204}:
            assert client.trash_page("42") is None
        else:
            with pytest.raises(ConfluenceAPIError) as excinfo:
                client.trash_page("42")
            assert excinfo.value.status_code == (403 if status == 403 else None)
    finally:
        client.close()


def test_attachment_lookup_and_multipart_upload_use_existing_auth_and_context_path(image_file):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer example-token"
        assert request.url.path == "/confluence/rest/api/content/42/child/attachment"
        if request.method == "GET":
            assert request.url.params["filename"] == "image.png"
            return httpx.Response(200, json={"results": [{"id": "91", "title": "image.png"}]})
        assert request.method == "POST" and request.headers["x-atlassian-token"] == "no-check"
        assert request.url.params["allowDuplicated"] == "false"
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        assert b'name="file"; filename="image.png"' in request.content
        assert b"Content-Type: image/png" in request.content
        assert image_file.read_bytes() in request.content
        return httpx.Response(200, json={"results": [{"id": "92", "title": "image.png"}]})

    client = ConfluenceClient(ConfluenceSettings("https://wiki.example/confluence", "example-token", None))
    client._client.close()
    client._client = httpx.Client(
        base_url="https://wiki.example/confluence/rest/api/", headers={"Authorization": "Bearer example-token"},
        transport=httpx.MockTransport(handle),
    )
    try:
        assert client.get_attachment("42", "image.png")["id"] == "91"
        assert client.upload_attachment("42", "image.png", image_file.read_bytes(), "image/png")["id"] == "92"
    finally:
        client.close()
    assert len(requests) == 2


@pytest.mark.parametrize("status,body", [(403, {}), (200, {"results": []}), (200, {"results": [{"id": "1", "title": "wrong.png"}]})])
def test_unconfirmed_attachment_upload_is_not_success(status, body):
    client = _transport_client(lambda request: httpx.Response(status, json=body))
    try:
        with pytest.raises(ConfluenceAPIError) as excinfo:
            client.upload_attachment("42", "image.png", b"image", "image/png")
        assert excinfo.value.status_code == (403 if status == 403 else None)
    finally:
        client.close()


@pytest.mark.parametrize("error_type,expected_type,message", [
    (httpx.ConnectError, ConfluenceConnectionError, "Could not connect"),
    (httpx.ConnectTimeout, ConfluenceConnectionError, "connecting to Confluence"),
    (httpx.PoolTimeout, ConfluenceConnectionError, "connection pool"),
    (httpx.ReadTimeout, ConfluenceAPIError, "waiting for the Confluence response"),
    (httpx.WriteTimeout, ConfluenceAPIError, "sending the Confluence request"),
])
def test_request_timeouts_identify_the_phase(error_type, expected_type, message):
    def handle(request):
        raise error_type("sample timeout", request=request)

    client = _transport_client(handle)
    try:
        with pytest.raises(ConfluenceAPIError, match=message) as excinfo:
            client.upload_attachment("42", "image.png", b"image", "image/png")
        assert type(excinfo.value) is expected_type
        assert excinfo.value.status_code is None
    finally:
        client.close()


@pytest.mark.parametrize("regular,upload_read,upload_write", [(30.0, 120.0, 120.0), (45.0, 150.0, 175.5)])
def test_upload_uses_its_own_read_and_write_timeouts(regular, upload_read, upload_write, tmp_path, monkeypatch):
    from confluence_mcp import settings_file

    if regular != 30.0:
        path = tmp_path / ".env"
        path.write_text(
            "ATLASSIAN_CONFLUENCE_URL=https://wiki.example/confluence\n"
            "ATLASSIAN_CONFLUENCE_PAT=example-token\n"
            f"CONFLUENCE_REQUEST_TIMEOUT_SECONDS={regular}\n"
            f"CONFLUENCE_ATTACHMENT_UPLOAD_READ_TIMEOUT_SECONDS={upload_read}\n"
            f"CONFLUENCE_ATTACHMENT_UPLOAD_WRITE_TIMEOUT_SECONDS={upload_write}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(settings_file, "get_settings", lambda: settings_file.load_env_file(path))
        settings = ConfluenceSettings.from_environment()
    else:
        settings = ConfluenceSettings("https://wiki.example/confluence", "example-token", None)
    timeouts = []

    def handle(request):
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, json={"results": [{"id": "92", "title": "image.png"}]})

    client = _transport_client(handle, settings)
    try:
        client.get_current_user()
        client.upload_attachment("42", "image.png", b"image", "image/png")
    finally:
        client.close()
    assert timeouts == [
        {"connect": 10.0, "read": regular, "write": regular, "pool": regular},
        {"connect": 10.0, "read": upload_read, "write": upload_write, "pool": regular},
    ]
