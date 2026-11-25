"""Client for the Confluence Server/Data Center REST API."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from . import settings_file


# Tool positions -> the values the Confluence move dialog posts to movepage.action.
MOVE_POSITIONS = {"before": "above", "after": "below", "append": "append"}


class ConfluenceConfigurationError(RuntimeError):
    """Raised when required connection settings are missing or invalid."""


class ConfluenceAPIError(RuntimeError):
    """Raised when a Confluence request fails or cannot be confirmed."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConfluenceConnectionError(ConfluenceAPIError):
    """A connection could not be obtained before the request was sent."""


def _timeout_seconds(settings: dict[str, str], key: str, default: float) -> float:
    try:
        seconds = float(settings.get(key, str(default)))
        if math.isfinite(seconds) and seconds > 0:
            return seconds
    except ValueError:
        pass
    raise ConfluenceConfigurationError(f"{key} in .env must be a positive, finite number of seconds.")


@dataclass(frozen=True)
class ConfluenceSettings:
    base_url: str
    pat: str = field(repr=False)
    ca_bundle: str | None
    request_timeout_seconds: float = 30.0
    attachment_upload_read_timeout_seconds: float = 120.0
    attachment_upload_write_timeout_seconds: float = 120.0

    @classmethod
    def from_environment(cls) -> "ConfluenceSettings":
        settings = settings_file.get_settings()
        raw_url = settings.get("ATLASSIAN_CONFLUENCE_URL", "").strip()
        if not raw_url:
            raise ConfluenceConfigurationError(
                "Set ATLASSIAN_CONFLUENCE_URL in the project root .env to the Confluence "
                "base URL, including any context path such as /confluence."
            )

        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfluenceConfigurationError(
                "ATLASSIAN_CONFLUENCE_URL must be an absolute http:// or https:// URL."
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfluenceConfigurationError(
                "ATLASSIAN_CONFLUENCE_URL must not contain credentials, a query, or a fragment."
            )
        normalized_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))

        pat = settings.get("ATLASSIAN_CONFLUENCE_PAT", "").strip()
        if not pat:
            raise ConfluenceConfigurationError(
                "Set ATLASSIAN_CONFLUENCE_PAT in the project root .env."
            )

        ca_bundle = settings.get("ATLASSIAN_CONFLUENCE_CA_BUNDLE", "").strip() or None
        return cls(
            normalized_url, pat, ca_bundle,
            request_timeout_seconds=_timeout_seconds(settings, settings_file.REQUEST_TIMEOUT_SECONDS, 30.0),
            attachment_upload_read_timeout_seconds=_timeout_seconds(
                settings, settings_file.ATTACHMENT_UPLOAD_READ_TIMEOUT_SECONDS, 120.0,
            ),
            attachment_upload_write_timeout_seconds=_timeout_seconds(
                settings, settings_file.ATTACHMENT_UPLOAD_WRITE_TIMEOUT_SECONDS, 120.0,
            ),
        )


class ConfluenceClient:
    """A wrapper around Confluence REST API v1."""

    def __init__(self, settings: ConfluenceSettings) -> None:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {settings.pat}"}
        timeout = httpx.Timeout(settings.request_timeout_seconds, connect=10.0)

        self._client = httpx.Client(
            base_url=f"{settings.base_url}/rest/api/",
            headers=headers,
            verify=settings.ca_bundle or True,
            timeout=timeout,
            follow_redirects=False,
        )
        self._base_url = settings.base_url
        self._attachment_upload_timeout = httpx.Timeout(
            connect=timeout.connect, read=settings.attachment_upload_read_timeout_seconds,
            write=settings.attachment_upload_write_timeout_seconds, pool=timeout.pool,
        )

    def close(self) -> None:
        self._client.close()

    def get_current_user(self) -> dict[str, Any]:
        return self._get_json("user/current", params={})

    def _validate_page_id(self, page_id: str) -> None:
        if not re.fullmatch(r"[0-9]+", page_id):
            raise ValueError("page_id must contain only digits.")

    def get_page(self, page_id: str) -> dict[str, Any]:
        self._validate_page_id(page_id)
        return self._get_json(
            f"content/{page_id}",
            params={"expand": "body.storage,body.view,version,space,ancestors"},
        )

    def search_pages(self, cql: str, limit: int) -> list[dict[str, Any]]:
        payload = self._get_json(
            "content/search",
            params={"cql": cql, "limit": limit, "expand": "space,version"},
        )
        return payload.get("results", [])

    def search_cql(self, cql: str, *, limit: int, start: int) -> dict[str, Any]:
        return self._get_json(
            "search",
            params={
                "cql": cql,
                "limit": limit,
                "start": start,
                "expand": "content.space,content.version",
            },
        )

    def list_spaces(self, *, limit: int, start: int) -> dict[str, Any]:
        return self._get_json("space", params={"type": "global", "limit": limit, "start": start})

    def get_comments(self, page_id: str, *, limit: int) -> list[dict[str, Any]]:
        self._validate_page_id(page_id)
        payload = self._get_json(
            f"content/{page_id}/child/comment",
            params={
                "expand": "body.storage,version,history",
                "depth": "all",
                "limit": limit,
            },
        )
        return payload.get("results", [])

    def get_child_pages(self, page_id: str, *, limit: int) -> list[dict[str, Any]]:
        self._validate_page_id(page_id)
        payload = self._get_json(
            f"content/{page_id}/child/page",
            params={"expand": "space,version", "limit": limit},
        )
        return payload.get("results", [])

    def list_versions(self, page_id: str) -> list[dict[str, Any]]:
        self._validate_page_id(page_id)
        last_error: ConfluenceAPIError | None = None
        for path in (
            f"content/{page_id}/version",
            f"../experimental/content/{page_id}/version",
        ):
            try:
                return self._get_json(path, params={"limit": 100}).get("results", [])
            except ConfluenceAPIError as exc:
                if exc.status_code not in (404, 405):
                    raise
                last_error = exc
        raise ConfluenceAPIError(
            "Confluence exposed no version-history endpoint at /rest/api/content/{id}/version "
            "or /rest/experimental/content/{id}/version, and the page may not exist.",
            status_code=last_error.status_code if last_error else None,
        )

    def get_page_version(self, page_id: str, version: int) -> dict[str, Any]:
        self._validate_page_id(page_id)
        return self._get_json(
            f"content/{page_id}",
            params={
                "status": "historical",
                "version": version,
                "expand": "body.storage,version,space",
            },
        )

    def create_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "content", json_body=payload)

    def update_page(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_page_id(page_id)
        return self._request_json("PUT", f"content/{page_id}", json_body=payload)

    def trash_page(self, page_id: str) -> None:
        self._validate_page_id(page_id)
        response = self._request("DELETE", f"content/{page_id}")
        if response.status_code not in {200, 204}:
            raise ConfluenceAPIError(f"Confluence did not confirm the move to trash (HTTP {response.status_code}).")

    def get_attachment(self, page_id: str, filename: str) -> dict[str, Any] | None:
        self._validate_page_id(page_id)
        response = self._get_json(
            f"content/{page_id}/child/attachment", params={"filename": filename},
        )
        return next((item for item in response.get("results", []) if item.get("title") == filename), None)

    def upload_attachment(
        self, page_id: str, filename: str, data: bytes, content_type: str,
    ) -> dict[str, Any]:
        self._validate_page_id(page_id)
        response = self._request_json(
            "POST", f"content/{page_id}/child/attachment",
            params={"allowDuplicated": "false"},
            files={"file": (filename, data, content_type)},
            headers={"X-Atlassian-Token": "no-check"},
            timeout=self._attachment_upload_timeout,
        )
        for item in response.get("results", []):
            if item.get("title") == filename and item.get("id"):
                return item
        raise ConfluenceAPIError("Confluence did not confirm the uploaded attachment; check the page attachments.")

    def move_page(self, page_id: str, position: str, target_id: str) -> dict[str, Any]:
        """Move a page before/after a sibling of target_id, or append it under target_id.

        Uses the undocumented movepage.action form that the Data Center page tree posts. It is
        not under /rest/api, so it is built from the site root. Success is the JSON answer's
        completedSuccessfully flag, never the HTTP status alone.
        """
        self._validate_page_id(page_id)
        self._validate_page_id(target_id)
        if position not in MOVE_POSITIONS:
            raise ValueError(f"position must be one of {', '.join(MOVE_POSITIONS)}.")
        try:
            response = self._client.request(
                "POST",
                self._site_url("pages/movepage.action"),
                data={
                    "pageId": page_id,
                    "position": MOVE_POSITIONS[position],
                    "targetId": target_id,
                    "mode": "LEGACY",
                },
                headers={"X-Atlassian-Token": "no-check"},
            )
        except httpx.TimeoutException as exc:
            raise ConfluenceAPIError("The Confluence request timed out.") from exc
        except httpx.ConnectError as exc:
            raise ConfluenceAPIError("Could not connect to Confluence.") from exc
        if response.status_code != 200:
            raise ConfluenceAPIError(
                f"Confluence returned HTTP {response.status_code} for the page move.",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ConfluenceAPIError("Confluence returned a non-JSON answer to the move.") from exc
        if not isinstance(body, dict) or not body.get("authorized", False):
            raise ConfluenceAPIError("Confluence did not authorize the move.", status_code=401)
        progress = body.get("progressMeter") or {}
        if not progress.get("completedSuccessfully") or body.get("validationErrors"):
            raise ConfluenceAPIError(
                f"Confluence refused the move: {body.get('validationErrors') or body}",
                status_code=200,
            )
        return body

    def _site_url(self, path: str) -> str:
        return f"{self._base_url}/{path}"

    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("GET", path, params=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method, path, params=params, json=json_body, files=files, headers=headers,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
        except httpx.ConnectTimeout as exc:
            raise ConfluenceConnectionError("The client timed out connecting to Confluence before sending the request.") from exc
        except httpx.PoolTimeout as exc:
            raise ConfluenceConnectionError(
                "The client timed out waiting for the Confluence connection pool before sending the request."
            ) from exc
        except httpx.WriteTimeout as exc:
            raise ConfluenceAPIError("The client timed out sending the Confluence request.") from exc
        except httpx.ReadTimeout as exc:
            raise ConfluenceAPIError("The client timed out waiting for the Confluence response.") from exc
        except httpx.TimeoutException as exc:
            raise ConfluenceAPIError("The Confluence request timed out.") from exc
        except httpx.ConnectError as exc:
            raise ConfluenceConnectionError(
                "Could not connect to Confluence. Check the URL, network/VPN, and TLS CA settings."
            ) from exc
        except httpx.RequestError as exc:
            raise ConfluenceAPIError("Confluence network request failed. Check the network/VPN.") from exc

        if response.is_redirect:
            raise ConfluenceAPIError(
                "Confluence redirected the API request. Check the base URL and context path; "
                "the server does not follow redirects to avoid sending credentials elsewhere.",
                status_code=response.status_code,
            )
        if response.status_code == 401:
            raise ConfluenceAPIError(
                "Confluence returned 401: credentials are missing, invalid, or expired.",
                status_code=401,
            )
        if response.status_code == 403:
            raise ConfluenceAPIError(
                "Confluence returned 403: the account lacks permission for this operation. "
                "For writes, also check CONFLUENCE_WRITE_SPACES and the space's edit restrictions.",
                status_code=403,
            )
        if response.status_code == 404:
            raise ConfluenceAPIError(
                "Confluence returned 404: check the page ID and base URL context path; "
                "a page hidden by permissions may also appear unavailable.",
                status_code=404,
            )
        if response.status_code == 409 and method == "PUT":
            raise ConfluenceAPIError(
                "Confluence rejected the update because the page version changed (HTTP 409). "
                "Re-read the page and retry with the current version.",
                status_code=409,
            )
        if response.is_error:
            raise ConfluenceAPIError(
                f"Confluence returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        return response

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            method, path, params=params, json_body=json_body, files=files, headers=headers, timeout=timeout,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConfluenceAPIError("Confluence returned a non-JSON response; check the base URL.") from exc
        if not isinstance(payload, dict):
            raise ConfluenceAPIError("Confluence returned an unexpected response shape.")
        return payload

    def absolute_url(self, path: str | None, *, base: str | None = None) -> str | None:
        if not path:
            return None
        response_base = base or self._base_url
        return urljoin(response_base.rstrip("/") + "/", path.lstrip("/"))

    def page_url(self, page: dict[str, Any]) -> str | None:
        links = page.get("_links") or {}
        return self.absolute_url(links.get("webui"), base=links.get("base"))


@lru_cache(maxsize=1)
def get_client() -> ConfluenceClient:
    return ConfluenceClient(ConfluenceSettings.from_environment())


def quote_cql(value: str) -> str:
    """Escape a value embedded in a quoted CQL string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
