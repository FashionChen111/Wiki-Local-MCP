import httpx
import pytest

from confluence_mcp import apply, queue, server, writes
from confluence_mcp.client import ConfluenceAPIError, ConfluenceClient, ConfluenceConnectionError, ConfluenceSettings


@pytest.fixture(autouse=True)
def page_client(fake_client, config_values, monkeypatch, tmp_path):
    config_values["CONFLUENCE_ENABLE_WRITES"] = "true"
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    fake_client.pages["42"] = {
        "id": "42", "title": "Guide", "space": {"key": "OPS"}, "version": {"number": 3},
        "body": {"storage": {"value": "<h2>Setup</h2><p>old</p><h2>Keep</h2><p>unchanged</p>"}},
    }
    fake_client.create_response = {"id": "77", "version": {"number": 1}}
    fake_client.update_response = {"id": "42", "version": {"number": 4}}


def _page_image(action, image_file, dry_run=False):
    markdown = f"![流程图]({image_file.name})"
    kwargs = {"image_base_dir": str(image_file.parent), "dry_run": dry_run}
    if action == "create":
        return server.create_page("OPS", "New guide", markdown, **kwargs)
    if action == "section":
        return server.update_page_section("42", "Setup", markdown, expected_version=3, **kwargs)
    return server.update_page("42", expected_version=3, content=markdown, **kwargs)


@pytest.mark.parametrize("action", ["create", "update", "section"])
def test_page_image_dry_run_only_previews_and_queue_only_snapshots(action, fake_client, image_file):
    preview = _page_image(action, image_file, dry_run=True)
    assert preview["attachments"][0]["source"] == str(image_file.resolve())
    assert "ri:attachment" in preview["storage_preview"]
    assert queue.list_ops() == []
    queued = _page_image(action, image_file)
    op = queue.get_op(queued["operation_id"])
    assert op["status"] == "pending" and "ri:attachment" in op["payload"]["body"]["storage"]["value"]
    assert fake_client.created == fake_client.updated == fake_client.uploaded == []
    assert server.get_queued_operations([op["id"]])["operations"][0]["attachments"] == preview["attachments"]


@pytest.mark.parametrize("action", ["create", "update", "section"])
def test_approval_uploads_snapshot_and_publishes_attachment_references_once(action, fake_client, image_file):
    op_id = _page_image(action, image_file)["operation_id"]
    snapshot = image_file.read_bytes()
    image_file.unlink()  # Approval is independent of the original file's lifetime.
    if action == "create":
        fake_client.update_response = {"id": "77", "version": {"number": 2}}
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "succeeded"
    [upload] = fake_client.uploaded
    assert upload[0] == ("77" if action == "create" else "42") and upload[2] == snapshot
    [published] = fake_client.updated
    assert f'ri:filename="{upload[1]}"' in published["body"]["storage"]["value"]
    assert published["version"]["number"] == (2 if action == "create" else 4)
    assert "uploaded_attachments" not in published
    if action == "create":
        assert "ri:attachment" not in fake_client.created[0]["body"]["storage"]["value"]
        assert out["result"]["id"] == "77"
    if action == "section":
        assert published["body"]["storage"]["value"].endswith("<h2>Keep</h2><p>unchanged</p>")
    assert apply.approve_and_apply(fake_client, [op_id])["executed"] == []
    assert len(fake_client.uploaded) == len(fake_client.updated) == 1


@pytest.mark.parametrize("changed", ["version", "space"])
def test_changed_page_version_or_space_fails_before_any_upload(fake_client, image_file, changed):
    op_id = _page_image("update", image_file)["operation_id"]
    if changed == "version":
        fake_client.pages["42"]["version"]["number"] = 4
    else:
        fake_client.pages["42"]["space"]["key"] = "QA"
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "failed" and fake_client.uploaded == fake_client.updated == []


def test_existing_content_addressed_attachment_is_reused(fake_client, image_file):
    op_id = _page_image("update", image_file)["operation_id"]
    [image] = queue.get_attachments(op_id)
    fake_client.attachments[("42", image.filename)] = {"id": "100", "title": image.filename}
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "succeeded" and fake_client.uploaded == []
    assert out["result"]["reused_attachments"] == [image.filename]


def test_failed_upload_keeps_created_page_id_and_stops_before_publishing(fake_client, image_file):
    op_id = _page_image("create", image_file)["operation_id"]

    def denied(*args):
        raise ConfluenceAPIError("upload forbidden", status_code=403)

    fake_client.upload_attachment = denied
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "failed" and out["result"]["id"] == "77"
    assert out["result"]["page_created"] and out["result"]["uploaded_attachments"] == []
    assert queue.get_op(op_id)["result"] == out["result"]
    assert fake_client.updated == []
    assert '"result": "partial"' in writes.AUDIT_PATH.read_text(encoding="utf-8")


def test_final_version_conflict_records_uploaded_files_without_overwriting_page(fake_client, image_file):
    op_id = _page_image("update", image_file)["operation_id"]

    def conflict(*args):
        raise ConfluenceAPIError("version conflict", status_code=409)

    fake_client.update_page = conflict
    out = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert out["status"] == "failed" and len(fake_client.uploaded) == 1
    assert out["result"]["version"] == 3
    assert out["result"]["uploaded_attachments"] == [fake_client.uploaded[0][1]]
    assert queue.get_op(op_id)["result"] == out["result"]


def test_upload_timeout_preserves_progress_and_stops_batch(fake_client, image_file):
    op_id = _page_image("create", image_file)["operation_id"]
    next_op = server.create_page("OPS", "Next", "body", dry_run=False)["operation_id"]

    def timeout(*args):
        # A crash/timeout must leave the already-known page id durable.
        assert queue.get_op(op_id)["result"]["id"] == "77"
        raise ConfluenceAPIError("timed out")

    fake_client.upload_attachment = timeout
    out = apply.approve_and_apply(fake_client, [op_id, next_op])
    assert out["executed"][0]["status"] == "indeterminate" and out["skipped"] == [next_op]
    assert queue.get_op(next_op)["status"] == "pending"


def test_second_upload_failure_keeps_first_upload_and_failed_filename(fake_client, image_file):
    second = image_file.with_name("second.svg")
    second.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>', encoding="utf-8")
    op_id = server.create_page(
        "OPS", "Two images", f"![a]({image_file.name}) ![b]({second.name})",
        image_base_dir=str(image_file.parent), dry_run=False,
    )["operation_id"]
    original_upload = fake_client.upload_attachment

    def upload(page_id, filename, data, content_type):
        if fake_client.uploaded:
            raise ConfluenceAPIError("denied", status_code=403)
        return original_upload(page_id, filename, data, content_type)

    fake_client.upload_attachment = upload
    result = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    first_image, second_image = queue.get_attachments(op_id)
    assert result["status"] == "failed" and fake_client.updated == []
    assert result["result"]["uploaded_attachments"] == [first_image.filename]
    assert result["result"]["failed_attachment"] == second_image.filename
    assert "uploading_attachment" not in result["result"]
    assert queue.get_op(op_id)["result"] == result["result"]


@pytest.mark.parametrize("configured,failures,status,attempts", [
    (None, 1, "failed", 1),
    ("2", 2, "succeeded", 3),
    ("2", 3, "failed", 3),
])
def test_upload_retries_only_the_attachment_within_the_budget(
    configured, failures, status, attempts, config_values, fake_client, image_file, monkeypatch
):
    if configured is not None:
        config_values["CONFLUENCE_ATTACHMENT_UPLOAD_RETRIES"] = configured
    monkeypatch.setattr(apply, "sleep", lambda delay: None)
    op_id = _page_image("create", image_file)["operation_id"]
    fake_client.update_response = {"id": "77", "version": {"number": 2}}
    original_upload = fake_client.upload_attachment
    [image] = queue.get_attachments(op_id)
    calls = []

    def upload(*args):
        calls.append(args)
        progress = queue.get_op(op_id)["result"]
        assert progress["uploading_attachment"] == image.filename
        if len(calls) <= failures:
            raise ConfluenceConnectionError("Unable to connect for image upload")
        return original_upload(*args)

    fake_client.upload_attachment = upload
    result = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert result["status"] == status and len(calls) == attempts
    assert len(fake_client.created) == 1
    assert len(fake_client.updated) == int(status == "succeeded")
    assert "uploading_attachment" not in result["result"]
    if status == "failed":
        assert result["result"]["failed_attachment"] == image.filename
    else:
        assert result["result"]["uploaded_attachments"] == [image.filename]
    assert result["result"].get("attachment_upload_retries", {}).get(image.filename, 0) == attempts - 1
    assert server.get_queued_operations([op_id])["operations"][0]["result"] == result["result"]


@pytest.mark.parametrize("status_code", [None, 502, 503, 504])
def test_unconfirmed_upload_is_never_retried(status_code, config_values, fake_client, image_file):
    config_values["CONFLUENCE_ATTACHMENT_UPLOAD_RETRIES"] = "2"
    op_id = _page_image("update", image_file)["operation_id"]
    attempts = []

    def upload(page_id, filename, *_):
        attempts.append(filename)
        raise ConfluenceAPIError("Upload not confirmed", status_code=status_code)

    fake_client.upload_attachment = upload
    result = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert result["status"] == "indeterminate" and fake_client.updated == []
    assert attempts == [result["result"]["uploading_attachment"]]


def test_read_timeout_keeps_the_attachment_unconfirmed(config_values, fake_client, image_file, monkeypatch):
    config_values["CONFLUENCE_ATTACHMENT_UPLOAD_RETRIES"] = "2"
    op_id = _page_image("create", image_file)["operation_id"]
    [image] = queue.get_attachments(op_id)
    posts = []

    def delayed_response(request):
        posts.append(request.method)
        assert image.data in request.content
        raise httpx.ReadTimeout("timeout awaiting response", request=request)

    client = ConfluenceClient(ConfluenceSettings("https://wiki.example", "example-token", None))
    client.close()
    with httpx.Client(base_url="https://wiki.example/rest/api/", transport=httpx.MockTransport(delayed_response)) as transport:
        client._client = transport
        monkeypatch.setattr(fake_client, "upload_attachment", client.upload_attachment)
        outcome = apply.approve_and_apply(fake_client, [op_id])["executed"][0]

    assert outcome["status"] == "indeterminate"
    assert "waiting for the Confluence response" in outcome["error"]
    assert outcome["result"]["uploading_attachment"] == image.filename
    assert outcome["result"]["attachment_upload_retries"][image.filename] == 0
    assert posts == ["POST"] and fake_client.updated == []


@pytest.mark.parametrize("configured", ["-1", "two"])
def test_invalid_retry_setting_fails_before_creating_the_placeholder(configured, config_values, fake_client, image_file):
    config_values["CONFLUENCE_ATTACHMENT_UPLOAD_RETRIES"] = configured
    op_id = _page_image("create", image_file)["operation_id"]
    result = apply.approve_and_apply(fake_client, [op_id])["executed"][0]
    assert result["status"] == "failed" and "CONFLUENCE_ATTACHMENT_UPLOAD_RETRIES" in result["error"]
    assert fake_client.created == fake_client.uploaded == fake_client.updated == []


def test_missing_image_does_not_queue_a_broken_page(fake_client, tmp_path):
    with pytest.raises(ValueError, match="Could not read image"):
        server.create_page("OPS", "New", "![x](missing.png)", image_base_dir=str(tmp_path), dry_run=False)
    assert queue.list_ops() == [] and fake_client.created == []
