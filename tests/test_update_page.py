import pytest

from confluence_mcp import apply, queue, server, writes
from confluence_mcp.client import ConfluenceAPIError


def page(version=3, storage="<p>old</p>"):
    return {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": version},
        "_links": {"webui": "/spaces/OPS/pages/42"},
        "body": {"storage": {"value": storage}},
    }


def test_update_page_dry_run_diffs_without_putting(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page("42", expected_version=3, content="new", dry_run=True)

    assert result["dry_run"] is True
    assert result["version_before"] == 3
    assert result["version_after"] == 4
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]
    assert fake_client.updated == []


@pytest.mark.parametrize("force", [False, True])
def test_update_page_rejects_stale_expected_version(fake_client, monkeypatch, config_values, force):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(version=4)

    with pytest.raises(ConfluenceAPIError, match="current version is 4"):
        server.update_page("42", expected_version=3, content="new", force=force)


def test_update_page_can_publish_a_fenced_code_block_twice(fake_client, monkeypatch, config_values, tmp_path):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    example = '<ac:structured-macro ac:name="info"/>'
    fenced_code = f"```text\n{example}\n```"

    fake_client.create_response = page(version=1)
    created = server.create_page("OPS", "Guide", fenced_code, dry_run=False)
    [creation] = apply.approve_and_apply(fake_client, [created["operation_id"]])["executed"]
    assert creation["status"] == "succeeded"
    storage = fake_client.created[0]["body"]["storage"]["value"]

    for version in (1, 2):
        # Confluence adds metadata to the macro it sends back with the page.
        returned_storage = storage.replace(
            '<ac:structured-macro ac:name="code">',
            "<ac:structured-macro ac:schema-version='1' ac:name='code' ac:macro-id='code-42'>",
        )
        fake_client.pages["42"] = page(version, returned_storage)
        fake_client.update_response = page(version=version + 1)
        queued = server.update_page(
            "42", expected_version=version, content=f"Update {version}\n\n{fenced_code}", dry_run=False,
        )
        [published] = apply.approve_and_apply(fake_client, [queued["operation_id"]])["executed"]
        assert (published["status"], published["result"]["version"]) == ("succeeded", version + 1)
        storage = fake_client.updated[-1]["body"]["storage"]["value"]
        assert '<ac:structured-macro ac:name="code">' in storage
        assert '<ac:parameter ac:name="language">text</ac:parameter>' in storage
        assert f"<![CDATA[{example}\n]]>" in storage


@pytest.mark.parametrize(("storage", "blocked_names"), [
    ('<ac:structured-macro ac:name="info"/><p>old</p>', ("info",)),
    (
        '<ac:structured-macro ac:name="code"/>'
        "<ac:structured-macro ac:schema-version='1' ac:name='panel'><ac:rich-text-body>"
        '<ac:structured-macro ac:name="jira"/></ac:rich-text-body></ac:structured-macro>',
        ("jira", "panel"),
    ),
])
def test_update_page_names_macros_that_markdown_cannot_preserve(
    fake_client, monkeypatch, config_values, storage, blocked_names,
):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage=storage)

    with pytest.raises(ConfluenceAPIError, match="update_page_section") as error:
        server.update_page("42", expected_version=3, content="new", dry_run=False)

    for name in blocked_names:
        assert name in str(error.value)
    assert "code" not in str(error.value)
    assert queue.list_ops() == []


def test_update_page_force_allows_markdown_on_macro_page(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage='<ac:structured-macro ac:name="toc"/><p>old</p>')

    result = server.update_page("42", expected_version=3, content="new", dry_run=True, force=True)

    assert result["dry_run"] is True and result["storage_preview"] == "<p>new</p>"


def test_update_page_accepts_storage_format(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage='<ac:structured-macro ac:name="toc"/><p>old</p>')

    result = server.update_page(
        "42",
        expected_version=3,
        content="<p>raw</p>",
        content_format="storage",
        dry_run=True,
    )

    assert "+raw" in result["diff"]


def test_update_page_queues_bound_payload(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page("42", expected_version=3, content="new", dry_run=False)

    assert result["queued"] is True and result["status"] == "pending"
    assert fake_client.updated == []
    [op] = queue.list_ops()
    assert op["id"] == result["operation_id"]
    assert op["kind"] == "update" and op["version_before"] == 3
    assert op["payload"]["version"]["number"] == 4
    assert op["payload"]["title"] == "Guide"
    assert "+new" in op["preview"]


def test_update_page_keeps_title_when_not_provided(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    server.update_page("42", expected_version=3, content="new", dry_run=False)

    assert queue.list_ops()[0]["payload"]["title"] == "Guide"


def test_update_page_rejects_empty_content(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="content"):
        server.update_page("42", expected_version=3, content="   ")


def test_update_page_rejects_empty_storage_content(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="content"):
        server.update_page("42", expected_version=3, content="", content_format="storage")
