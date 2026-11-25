"""Terminal review for Confluence writes queued by the MCP server."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from . import queue, web
from .apply import approve_and_apply, inspect_resume, resume_claimed
from .client import ConfluenceAPIError, ConfluenceConfigurationError, get_client
from .writes import WRITE_FLAG, writes_enabled


def _console_attached() -> bool:
    """True only on a real Windows console; NUL and other char devices also report isatty()."""
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    except (OSError, ValueError):
        return False
    mode = ctypes.c_uint32()
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def _interactive_stdin() -> bool:
    if not sys.stdin.isatty():
        return False
    return _console_attached() if sys.platform == "win32" else True


def _format(op: dict[str, Any]) -> str:
    header = (
        f"{op['id']}  {op['status']}  {op['action']}  "
        f"{op['space_key']}/{op['page_id']}  v{op['version_before']}  {op['summary']}"
    )
    preview = "\n".join(f"    {line}" for line in op["preview"].splitlines())
    images = "\n".join(
        f"    Image: {image['source']} -> {image['filename']} ({image['size_bytes']} bytes)"
        for image in queue.attachment_summaries(op["id"])
    )
    return "\n".join(part for part in (header, images, preview) if part)


def _show(ops: list[dict[str, Any]]) -> None:
    for op in ops:
        print(_format(op))


def _list(show_all: bool) -> int:
    statuses = None if show_all else ("pending", "approved")
    _show(queue.list_ops(statuses))
    return 0


def _approve(ids: list[str]) -> int:
    if not _interactive_stdin():
        print("approve needs an interactive terminal", file=sys.stderr)
        return 2
    if not writes_enabled():
        print(f"approve writes to Confluence; set {WRITE_FLAG}=true in the project root .env and restart", file=sys.stderr)
        return 2
    for op_id in queue.recover_stale_executing():
        print(f"interrupted earlier, outcome unknown (check Confluence): {op_id}")

    pending = queue.list_ops(("pending",))
    targets = [op for op in pending if not ids or op["id"] in ids]
    _show(targets)
    print(f"Approve and write {len(targets)} operation(s)? Type yes: ", end="", flush=True)
    if sys.stdin.readline().strip() != "yes":
        print("nothing approved")
        return 1

    target_ids = [op["id"] for op in targets]
    outcome = approve_and_apply(get_client(), target_ids)
    for done in outcome["executed"]:
        print(f"{done['operation_id']}: {done['status']}" + (f" ({done['error']})" if done["error"] else ""))
    for op_id in outcome["skipped"]:
        print(f"skipped: {op_id}")
    for op_id in [*(i for i in ids if i not in target_ids), *outcome["not_pending"]]:
        print(f"not pending: {op_id}")
    return 0


def _web() -> int:
    if not _interactive_stdin():
        print("web needs an interactive terminal", file=sys.stderr)
        return 2
    if not writes_enabled():
        print(f"web writes to Confluence; set {WRITE_FLAG}=true in the project root .env and restart", file=sys.stderr)
        return 2
    queue.recover_stale_executing()
    web.serve(get_client())
    return 0


def _resume(op_id: str) -> int:
    if not _interactive_stdin():
        print("resume needs an interactive terminal", file=sys.stderr)
        return 2
    if not writes_enabled():
        print(f"resume requires {WRITE_FLAG}=true in the project root .env", file=sys.stderr)
        return 2
    op = queue.get_op(op_id)
    if op is None or op["status"] != "indeterminate":
        print(f"not indeterminate: {op_id}", file=sys.stderr)
        return 1
    try:
        client = get_client()
        plan = inspect_resume(client, op)
    except (ValueError, ConfluenceConfigurationError, ConfluenceAPIError) as exc:
        print(f"{op_id}: {exc}", file=sys.stderr)
        return 1

    _show([op])
    print(f"Page {plan.page_id} · v{plan.base_version} → v{plan.target_version}")
    missing = set(plan.missing_attachments)
    existing = [item["filename"] for item in queue.attachment_summaries(op_id) if item["filename"] not in missing]
    print("Existing attachments: " + (", ".join(existing) or "none"))
    print("Missing attachments: " + (", ".join(plan.missing_attachments) or "none"))
    question = "Record the verified result" if plan.already_applied else "Resume this write"
    print(f"{question}? Type yes: ", end="", flush=True)
    if sys.stdin.readline().strip() != "yes":
        print("nothing resumed")
        return 1
    claimed = queue.claim_indeterminate(op_id, expected_updated_at=op["updated_at"])
    if claimed is None:
        print(f"operation changed during confirmation: {op_id}", file=sys.stderr)
        return 1
    outcome = resume_claimed(client, claimed)
    print(f"{op_id}: {outcome['status']}" + (f" ({outcome['error']})" if outcome["error"] else ""))
    return 0 if outcome["status"] == "succeeded" else 1


def _reject(ids: list[str]) -> int:
    for op_id in queue.reject(ids):
        print(f"rejected: {op_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="confluence-mcp-review",
        description="Review Confluence writes queued by the MCP server.",
    )
    subparsers = parser.add_subparsers(dest="command")
    list_parser = subparsers.add_parser("list", help="show pending and approved operations")
    list_parser.add_argument("--all", action="store_true", help="include finished operations")
    approve_parser = subparsers.add_parser("approve", help="approve pending operations")
    approve_parser.add_argument("ids", nargs="*")
    subparsers.add_parser("web", help="open the local approval page")
    reject_parser = subparsers.add_parser("reject", help="reject pending operations")
    reject_parser.add_argument("ids", nargs="+")
    resume_parser = subparsers.add_parser("resume", help="verify and resume an uncertain attachment write")
    resume_parser.add_argument("id")

    args = parser.parse_args(argv)
    if args.command == "approve":
        return _approve(args.ids)
    if args.command == "reject":
        return _reject(args.ids)
    if args.command == "web":
        return _web()
    if args.command == "resume":
        return _resume(args.id)
    return _list(getattr(args, "all", False))
