from confluence_mcp.markdown_storage import markdown_to_storage, unsupported_markdown_macros


def test_headings_lists_links_and_emphasis_become_html():
    storage = markdown_to_storage(
        "## Setup\n\n- one\n- two\n\n**bold** and *italic* [docs](https://x)"
    )

    assert "<h2>Setup</h2>" in storage
    assert "<li>one</li>" in storage
    assert "<strong>bold</strong>" in storage
    assert "<em>italic</em>" in storage
    assert '<a href="https://x">docs</a>' in storage


def test_table_becomes_html_table():
    storage = markdown_to_storage("| a | b |\n|---|---|\n| 1 | 2 |")

    assert "<table>" in storage
    assert "<td>1</td>" in storage


def test_fenced_code_becomes_confluence_code_macro():
    storage = markdown_to_storage("```python\nprint(1)\n```")

    assert '<ac:structured-macro ac:name="code">' in storage
    assert '<ac:parameter ac:name="language">python</ac:parameter>' in storage
    assert "<![CDATA[print(1)" in storage


def test_fence_without_language_still_becomes_code_macro():
    storage = markdown_to_storage("```\nplain\n```")

    assert '<ac:structured-macro ac:name="code">' in storage
    assert "ac:parameter" not in storage


def test_cdata_terminator_is_split():
    storage = markdown_to_storage("```\na ]]> b\n```")

    assert "a ]]]]><![CDATA[> b" in storage


def test_macro_protection_detects_unsupported_and_unnamed_elements():
    storage = (
        '<!-- <![CDATA[<ac:structured-macro ac:name="ignored"/> -->'
        '<ac:structured-macro ac:name="toc"/><ac:structured-macro ac:name="toc"/>'
        '<ac:structured-macro ac:schema-version="1"/>'
    )
    assert unsupported_markdown_macros(storage) == ["toc", "unnamed macro"]
    assert unsupported_markdown_macros("<p>plain</p>") == []


def test_inline_br_in_table_cell_is_self_closed():
    import xml.etree.ElementTree as ET

    storage = markdown_to_storage("| a | b |\n|---|---|\n| x<br>y | z |")

    assert "<br />" in storage and "<br>" not in storage
    ET.fromstring(f'<root xmlns:ac="ac" xmlns:ri="ri">{storage}</root>')  # well-formed XHTML
