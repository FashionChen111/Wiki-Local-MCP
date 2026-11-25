import json

import pytest

from confluence_mcp import apply, queue, server, writes
from confluence_mcp.client import ConfluenceAPIError


@pytest.fixture(autouse=True)
def deletion_target(fake_client, config_values, monkeypatch, tmp_path):
    config_values.update(CONFLUENCE_ENABLE_WRITES="true", CONFLUENCE_WRITE_SPACES="OPS")
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    fake_client.pages["42"] = {
        "id": "42", "title": "Test guide", "type": "page", "status": "current",
        "space": {"key": "OPS"}, "version": {"number": 3}, "ancestors": [{"id": "7", "title": "Runbooks"}],
    }


def test_delete_page_previews_and_queues_without_trashing(fake_client):
    preview = server.delete_page("42")
    assert preview["dry_run"] and preview["destination"] == "trash"
    assert (preview["page_id"], preview["parent_page_id"], preview["version_before"]) == ("42", "7", 3)
    assert queue.list_ops() == []

    queued = server.delete_page("42", dry_run=False)
    op = queue.get_op(queued["operation_id"])
    assert (op["status"], op["action"], op["page_id"]) == ("pending", "delete_page", "42")
    assert op["payload"]["parent_page_id"] == "7"
    assert not fake_client.trashed and "42" in fake_client.pages


def test_delete_page_rejection_and_approval_are_single_use(fake_client):
    first = server.delete_page("42", dry_run=False)["operation_id"]
    queue.reject([first], reason="保留测试页")
    assert apply.approve_and_apply(fake_client, [first])["executed"] == []
    assert fake_client.trashed == []

    second = server.delete_page("42", dry_run=False)["operation_id"]
    [result] = apply.approve_and_apply(fake_client, [second])["executed"]
    assert result["status"] == "succeeded"
    assert result["result"] == {"id": "42", "version": None, "url": None, "trashed": True}
    assert apply.approve_and_apply(fake_client, [second])["executed"] == []
    assert fake_client.trashed == ["42"]
    info = json.loads(writes.AUDIT_PATH.read_text(encoding="utf-8"))
    assert (info["action"], info["result"], info["page_id"], info["version_before"]) == ("delete_page", "trashed", "42", 3)
    assert queue.get_op(first)["result"]["rejection_reason"] == "保留测试页"


@pytest.mark.parametrize("changed,value", [
    ("space", {"key": "QA"}),
    ("version", {"number": 4}),
    ("ancestors", [{"id": "9"}]),
    ("status", "trashed"),
])
def test_delete_page_rechecks_the_target_before_sending(fake_client, changed, value):
    op_id = server.delete_page("42", dry_run=False)["operation_id"]
    fake_client.pages["42"][changed] = value
    [done] = apply.approve_and_apply(fake_client, [op_id])["executed"]
    assert done["status"] == "failed"
    assert fake_client.trashed == [] and "42" in fake_client.pages


def test_delete_page_rejects_incomplete_location(fake_client):
    del fake_client.pages["42"]["ancestors"]
    with pytest.raises(ConfluenceAPIError, match="parent"):
        server.delete_page("42", dry_run=False)
    assert queue.list_ops() == [] and fake_client.trashed == []


def test_delete_page_read_timeout_before_sending_is_a_known_failure(fake_client):
    op_id = server.delete_page("42", dry_run=False)["operation_id"]
    next_id = server.create_page("OPS", "Next guide", "body", dry_run=False)["operation_id"]
    fake_client.create_response = {"id": "77", "version": {"number": 1}}

    def target_timeout(page_id):
        raise ConfluenceAPIError("The client timed out waiting for the Confluence response.")

    fake_client.get_page = target_timeout
    batch = apply.approve_and_apply(fake_client, [op_id, next_id])
    assert [item["status"] for item in batch["executed"]] == ["failed", "succeeded"]
    assert batch["skipped"] == [] and fake_client.trashed == []


@pytest.mark.parametrize("code", [None, 403, 502])
def test_delete_page_records_unknown_outcomes_without_retrying(fake_client, code):
    op_id = server.delete_page("42", dry_run=False)["operation_id"]
    attempts = []

    def trash(page_id):
        attempts.append(page_id)
        raise ConfluenceAPIError("response not confirmed", status_code=code)

    fake_client.trash_page = trash
    [done] = apply.approve_and_apply(fake_client, [op_id])["executed"]
    assert done["status"] == ("failed" if code == 403 else "indeterminate")
    assert apply.approve_and_apply(fake_client, [op_id])["executed"] == []
    assert attempts == ["42"]
