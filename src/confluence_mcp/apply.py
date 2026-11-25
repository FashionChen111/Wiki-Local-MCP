"""Execute each approved Confluence write at most once."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from time import sleep
from typing import Any

from . import queue, settings_file
from .client import ConfluenceAPIError, ConfluenceConfigurationError, ConfluenceConnectionError
from .images import ImageAttachment
from .writes import audit_write, ensure_write_allowed, read_trash_target


@dataclass(frozen=True)
class ResumePlan:
    page_id: str
    base_version: int
    target_version: int
    missing_attachments: tuple[str, ...]
    already_applied: bool


def attachment_placeholder(operation_id: str) -> str:
    return f"<p>页面尚未发布。请在 Wiki MCP 审批记录中核对操作 ID {escape(operation_id)}。</p>"


def _attachment_upload_retries() -> int:
    key = settings_file.ATTACHMENT_UPLOAD_RETRIES
    raw = settings_file.get_settings().get(key, "0").strip() or "0"
    try:
        retries = int(raw)
        if retries >= 0:
            return retries
    except ValueError:
        pass
    raise ConfluenceConfigurationError(f"{key} in .env must be a non-negative integer.")


def _upload_attachment(
    client: Any, op_id: str, result: dict[str, Any], image: ImageAttachment, retries: int,
    *, before_write: Callable[[], None] | None,
) -> None:
    retries_by_filename = result.setdefault("attachment_upload_retries", {})
    previous_retries = retries_by_filename.get(image.filename, 0)
    for attempt in range(retries + 1):
        if before_write is not None:
            before_write()
        result["uploading_attachment"] = image.filename
        retries_by_filename[image.filename] = previous_retries + attempt
        queue.record_progress(op_id, result)
        try:
            client.upload_attachment(result["id"], image.filename, image.data, image.content_type)
        except ConfluenceConnectionError:
            if attempt == retries:
                raise
            sleep(0.5)
            continue
        except ConfluenceAPIError as exc:
            # A previous upload may become visible between the lookup and the POST.
            if exc.status_code not in {400, 409}:
                raise
            try:
                existing = client.get_attachment(result["id"], image.filename)
            except ConfluenceAPIError as lookup_error:
                raise ConfluenceAPIError(
                    f"Could not confirm the attachment after HTTP {exc.status_code}: {lookup_error}"
                ) from lookup_error
            if existing is None:
                raise
            _record_reused_attachment(result, image.filename)
        else:
            if image.filename in result["reused_attachments"]:
                result["reused_attachments"].remove(image.filename)
            if image.filename not in result["uploaded_attachments"]:
                result["uploaded_attachments"].append(image.filename)
        del result["uploading_attachment"]
        return


def _record_reused_attachment(result: dict[str, Any], filename: str) -> None:
    if filename not in result["uploaded_attachments"] and filename not in result["reused_attachments"]:
        result["reused_attachments"].append(filename)


def _publish_attachment_body(
    client: Any, op_id: str, payload: dict[str, Any], attachments: list[ImageAttachment],
    result: dict[str, Any], retries: int, *, before_write: Callable[[], None] | None = None,
) -> None:
    for image in attachments:
        if client.get_attachment(result["id"], image.filename) is not None:
            _record_reused_attachment(result, image.filename)
        else:
            _upload_attachment(client, op_id, result, image, retries, before_write=before_write)
        queue.record_progress(op_id, result)
    if before_write is not None:
        before_write()
    response = client.update_page(result["id"], payload)
    result.update(
        version=(response.get("version") or {}).get("number"),
        url=client.page_url(response),
    )


def _confirmed_write_failure(exc: ConfluenceAPIError) -> bool:
    return isinstance(exc, ConfluenceConnectionError) or 400 <= (exc.status_code or 0) < 500


def _record_failed_attachment(result: dict[str, Any]) -> None:
    if "uploading_attachment" in result:
        result["failed_attachment"] = result.pop("uploading_attachment")


def _error_with_resume_hint(
    op_id: str, status: str, result: dict[str, Any] | None, error: str | None,
) -> str | None:
    if status == "indeterminate" and error and result and result.get("uploading_attachment"):
        return (
            f"{error} Run 'confluence-mcp-review resume {op_id}' in an interactive terminal "
            "to check the attachment and resume the write."
        )
    return error


def _storage_body(content: dict[str, Any]) -> str | None:
    value = ((content.get("body") or {}).get("storage") or {}).get("value")
    return value.strip() if isinstance(value, str) else None


def _read_resume_page(client: Any, op: dict[str, Any], page_id: str) -> dict[str, Any]:
    page = client.get_page(page_id)
    if (str(page.get("id")) != page_id or page.get("type") != "page" or page.get("status") != "current"
            or (page.get("space") or {}).get("key") != op["space_key"]):
        raise ConfluenceAPIError("The original page or space changed before recovery.", status_code=409)
    return page


def _check_resume_base_version(op: dict[str, Any], page: dict[str, Any], base_version: int) -> None:
    if (
        (page.get("version") or {}).get("number") != base_version
        or (op["kind"] == "create" and _storage_body(page) not in {
            attachment_placeholder(op["id"]), "<p>Image upload in progress.</p>",
        })
    ):
        raise ConfluenceAPIError("The page version or placeholder changed before recovery.", status_code=409)


def inspect_resume(client: Any, op: dict[str, Any]) -> ResumePlan:
    """Check whether an uncertain attachment write can continue on its known page."""
    if op["status"] not in {"indeterminate", "executing"} or op["action"] not in {
        "create_page", "update_page", "update_page_section",
    }:
        raise ValueError("Only indeterminate page writes with attachments can be resumed.")
    if op["error"] == queue.INTERRUPTED_EXECUTION_ERROR:
        raise ValueError("The earlier process may still be running. Check the interrupted write in Confluence.")
    ensure_write_allowed(op["space_key"])
    result = op["result"] or {}
    page_id = str(result.get("id") or "")
    base_version = result.get("version")
    if not page_id.isascii() or not page_id.isdigit() or type(base_version) is not int or base_version < 1:
        raise ValueError("A confirmed page ID and version are required to resume.")
    target_version = base_version + 1
    payload = op["payload"]
    if op["kind"] == "update" and (
        op["page_id"] != page_id or op["version_before"] != base_version
        or (payload.get("version") or {}).get("number") != target_version
    ):
        raise ValueError("The recorded page or version no longer matches the queued update.")
    attachments = queue.attachment_summaries(op["id"])
    target_body = _storage_body(payload)
    if not attachments or not target_body or not isinstance(payload.get("title"), str):
        raise ValueError("The original body and attachment snapshots are required to resume.")

    page = _read_resume_page(client, op, page_id)
    already_applied = (
        (page.get("version") or {}).get("number") == target_version
        and _storage_body(page) == target_body and page.get("title") == payload["title"]
    )
    if not already_applied:
        _check_resume_base_version(op, page, base_version)

    missing = tuple(
        item["filename"] for item in attachments if client.get_attachment(page_id, item["filename"]) is None
    )
    if already_applied and missing:
        raise ConfluenceAPIError("The published page is missing one or more original attachments.", status_code=409)
    return ResumePlan(page_id, base_version, target_version, missing, already_applied)


def resume_claimed(client: Any, op: dict[str, Any]) -> dict[str, Any]:
    """Continue a write after the interactive terminal has confirmed and claimed it."""
    if op["status"] != "executing":
        raise ValueError("The operation must be claimed before resuming.")
    result = dict(op["result"] or {})
    version_before = result.get("version")
    pending_attachment = result.get("uploading_attachment")
    result["resume_attempts"] = result.get("resume_attempts", 0) + 1
    result.setdefault("error_before_resume", op["error"])
    status, error = "succeeded", None
    publishing = False
    try:
        plan = inspect_resume(client, op)
        attachments = queue.get_attachments(op["id"])
        missing = set(plan.missing_attachments)
        for key in ("uploaded_attachments", "reused_attachments"):
            result[key] = [name for name in result.get(key, []) if name not in missing]
        result.pop("uploading_attachment", None)
        result.pop("failed_attachment", None)
        if plan.already_applied:
            for image in attachments:
                _record_reused_attachment(result, image.filename)
            result["version"] = plan.target_version
        else:
            original = op["payload"]
            payload = {
                "id": plan.page_id, "type": "page", "title": original["title"], "body": original["body"],
                "version": {**original.get("version", {}), "number": plan.target_version},
            }
            retries = _attachment_upload_retries()

            def check_page_before_write() -> None:
                page = _read_resume_page(client, op, plan.page_id)
                _check_resume_base_version(op, page, plan.base_version)

            publishing = True
            _publish_attachment_body(
                client, op["id"], payload, attachments, result, retries, before_write=check_page_before_write,
            )
    except (ValueError, ConfluenceConfigurationError) as exc:
        status, error = "failed", str(exc)
    except ConfluenceConnectionError as exc:
        # A new pre-send failure leaves the earlier attempt unresolved.
        if publishing and result.get("uploading_attachment") != pending_attachment:
            _record_failed_attachment(result)
            if pending_attachment and all(
                pending_attachment not in result[key] for key in ("uploaded_attachments", "reused_attachments")
            ):
                result["uploading_attachment"] = pending_attachment
        status, error = "indeterminate", str(exc)
    except ConfluenceAPIError as exc:
        failed = _confirmed_write_failure(exc)
        if publishing and failed:
            _record_failed_attachment(result)
        status, error = ("failed" if failed else "indeterminate"), str(exc)
    except Exception as exc:
        status, error = "indeterminate", str(exc)

    error = _error_with_resume_hint(op["id"], status, result, error)
    queue.finish(op["id"], status, result=result, error=error)
    if result.get("id"):
        audit_write(
            "resume_operation", page_id=result["id"], space_key=op["space_key"],
            version_before=version_before, version_after=result.get("version"), result=status,
        )
    return {"operation_id": op["id"], "action": op["action"], "status": status, "result": result, "error": error}


def execute(client: Any, op: dict[str, Any]) -> dict[str, Any]:
    """Send one claimed (executing) operation and record how it ended."""
    status = "succeeded"
    result: dict[str, Any] | None = None
    error: str | None = None
    attempting_trash = False
    try:
        ensure_write_allowed(op["space_key"])
        attachments = queue.get_attachments(op["id"])
        if op["action"] == "delete_page":
            target = read_trash_target(client, op["page_id"])
            if (
                target.space_key != op["space_key"] or target.version != op["version_before"]
                or target.parent_page_id != op["payload"]["parent_page_id"]
            ):
                raise ConfluenceAPIError("The page version or location changed before deletion.", status_code=409)
            attempting_trash = True
            client.trash_page(op["page_id"])
            result = {"id": op["page_id"], "version": None, "url": None, "trashed": True}
        elif op["action"] == "move_page":
            payload = op["payload"]
            # movepage.action answers with the moved page, not a version, so record the page id only.
            client.move_page(op["page_id"], payload["position"], payload["target_id"])
            result = {"id": op["page_id"], "version": None, "url": None}
        elif attachments:
            retries = _attachment_upload_retries()
            payload = op["payload"]
            if op["kind"] == "create":
                # A page id is required before its attachments can be uploaded.
                response = client.create_content({
                    **payload,
                    "body": {"storage": {
                        "representation": "storage", "value": attachment_placeholder(op["id"]),
                    }},
                })
            else:
                response = client.get_page(op["page_id"])
                if ((response.get("version") or {}).get("number") != op["version_before"]
                        or (response.get("space") or {}).get("key") != op["space_key"]):
                    raise ConfluenceAPIError(
                        "The page version or space changed before image upload. Re-read the page and queue again.",
                        status_code=409,
                    )
            result = {
                "id": str(response["id"]),
                "version": (response.get("version") or {}).get("number"),
                "url": client.page_url(response),
                "page_created": op["kind"] == "create",
                "uploaded_attachments": [],
                "reused_attachments": [],
            }
            queue.record_progress(op["id"], result)
            if op["kind"] == "create":
                if not isinstance(result["version"], int):
                    raise ConfluenceAPIError("The new page version is unknown; check the created page before continuing.")
                payload = {**payload, "id": result["id"], "version": {"number": result["version"] + 1}}
            _publish_attachment_body(client, op["id"], payload, attachments, result, retries)
        elif op["kind"] == "update":
            response = client.update_page(op["page_id"], op["payload"])
            result = {
                "id": str(response["id"]),
                "version": (response.get("version") or {}).get("number"),
                "url": client.page_url(response),
            }
        else:
            response = client.create_content(op["payload"])
            result = {
                "id": str(response["id"]),
                "version": (response.get("version") or {}).get("number"),
                "url": client.page_url(response),
            }
    except ConfluenceConfigurationError as exc:
        status, error = "failed", str(exc)
    except ConfluenceAPIError as exc:
        failed = exc.status_code is not None
        if result and "page_created" in result:
            # A gateway error can follow an attachment POST or the final body PUT.
            failed = _confirmed_write_failure(exc)
            if failed:
                _record_failed_attachment(result)
        elif op["action"] == "delete_page":
            failed = not attempting_trash or _confirmed_write_failure(exc)
        status = "failed" if failed else "indeterminate"
        error = str(exc)
    except Exception as exc:
        status, error = "indeterminate", str(exc)

    if status == "succeeded":
        queue.finish(op["id"], "succeeded", result=result)
        audit_write(
            op["action"],
            page_id=op["page_id"] or result["id"],
            space_key=op["space_key"],
            version_before=op["version_before"],
            version_after=result["version"],
            result=(
                "trashed" if op["action"] == "delete_page"
                else "moved" if op["action"] == "move_page"
                else "updated" if op["kind"] == "update" else "created"
            ),
        )
    else:
        error = _error_with_resume_hint(op["id"], status, result, error)
        queue.finish(op["id"], status, result=result, error=error)
        if result and (result.get("page_created") or result.get("uploaded_attachments")):
            audit_write(
                op["action"], page_id=result["id"], space_key=op["space_key"],
                version_before=op["version_before"], version_after=result["version"],
                result="partial",
            )

    return {
        "operation_id": op["id"],
        "action": op["action"],
        "status": status,
        "result": result,
        "error": error,
    }


def approve_and_apply(client: Any, op_ids: list[str]) -> dict[str, Any]:
    """Approve and send operations in the given order.

    Pending operations are approved first; already-approved ones are sent as they are.
    Stops at the first indeterminate outcome and leaves the rest untouched.
    """
    executed: list[dict[str, Any]] = []
    not_pending: list[str] = []
    for index, op_id in enumerate(op_ids):
        op = queue.get_op(op_id)
        if op is not None and op["status"] == "pending":
            queue.approve([op_id])
        claimed = queue.claim_approved(op_id)
        if claimed is None:
            not_pending.append(op_id)
            continue
        outcome = execute(client, claimed)
        executed.append(outcome)
        if outcome["status"] == "indeterminate":
            return {
                "executed": executed,
                "not_pending": not_pending,
                "skipped": list(op_ids[index + 1 :]),
            }
    return {"executed": executed, "not_pending": not_pending, "skipped": []}
