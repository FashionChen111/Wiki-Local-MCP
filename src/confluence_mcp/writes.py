"""Guardrails for Confluence write operations."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import settings_file
from .client import ConfluenceAPIError, ConfluenceConfigurationError

WRITE_FLAG = "CONFLUENCE_ENABLE_WRITES"
WRITE_SPACES = "CONFLUENCE_WRITE_SPACES"
AUDIT_PATH = Path.home() / ".confluence-mcp" / "audit.log"


def writes_enabled() -> bool:
    return settings_file.get_settings().get(WRITE_FLAG, "").strip().lower() in {"1", "true", "yes"}


def ensure_write_allowed(space_key: str | None) -> None:
    if not writes_enabled():
        raise ConfluenceConfigurationError(
            f"Writes are disabled. Set {WRITE_FLAG}=true in the project root .env and restart."
        )
    allowed = {item.strip() for item in settings_file.get_settings().get(WRITE_SPACES, "").split(",") if item.strip()}
    if allowed and space_key not in allowed:
        raise ConfluenceConfigurationError(
            f'Space "{space_key}" is not in {WRITE_SPACES}. Allowed spaces: {", ".join(sorted(allowed))}.'
        )


@dataclass(frozen=True)
class TrashTarget:
    title: str
    space_key: str
    version: int
    parent_page_id: str | None


def read_trash_target(client: Any, page_id: str) -> TrashTarget:
    page = client.get_page(page_id)
    if str(page.get("id")) != page_id or page.get("type") != "page" or page.get("status") != "current":
        raise ConfluenceAPIError("Only the specified current page can be moved to the trash.", status_code=409)
    space_key = (page.get("space") or {}).get("key")
    version = (page.get("version") or {}).get("number")
    ancestors = page.get("ancestors")
    title = page.get("title")
    if (not isinstance(space_key, str) or not space_key or type(version) is not int or version < 1
            or not isinstance(ancestors, list) or not isinstance(title, str) or not title):
        raise ConfluenceAPIError("Could not confirm the page title, space, version or parent.", status_code=409)
    parent_page_id = None
    if ancestors:
        parent = ancestors[-1]
        if not isinstance(parent, dict) or not parent.get("id"):
            raise ConfluenceAPIError("Could not confirm the parent of the page.", status_code=409)
        parent_page_id = str(parent["id"])
    ensure_write_allowed(space_key)
    return TrashTarget(title, space_key, version, parent_page_id)


def audit_write(
    action: str,
    *,
    page_id: str,
    space_key: str | None,
    version_before: int | None,
    version_after: int | None,
    result: str,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "page_id": page_id,
        "space_key": space_key,
        "version_before": version_before,
        "version_after": version_after,
        "result": result,
    }
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Losing the audit line must not turn a successful write into a failure.
        print(f"confluence-mcp: could not write audit log: {exc}", file=sys.stderr)
