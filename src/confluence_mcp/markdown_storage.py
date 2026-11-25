"""Convert Markdown into Confluence storage XHTML."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

import markdown

_CODE_BLOCK = re.compile(
    r'<pre><code(?: class="language-([^"]+)")?>(.*?)</code>\s*</pre>',
    re.DOTALL,
)
_LITERAL_STORAGE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>", re.DOTALL)


def markdown_to_storage(markdown_text: str) -> str:
    rendered = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code"],
        output_format="xhtml",
    )
    # Raw inline <br> passes through Markdown unchanged; storage XHTML must self-close it or Confluence returns 400.
    return _CODE_BLOCK.sub(_code_macro, rendered.replace("<br>", "<br />"))


def _code_macro(match: re.Match[str]) -> str:
    language, code = match.group(1), html.unescape(match.group(2))
    # A literal ]]> would close the CDATA section early; split it per the XHTML spec.
    code = code.replace("]]>", "]]]]><![CDATA[>")
    if not code.endswith("\n"):
        code += "\n"
    parameter = (
        f'<ac:parameter ac:name="language">{html.escape(language)}</ac:parameter>'
        if language
        else ""
    )
    return (
        f'<ac:structured-macro ac:name="code">{parameter}'
        f"<ac:plain-text-body><![CDATA[{code}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


class _MacroCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.unsupported: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "ac:structured-macro":
            return
        name = dict(attrs).get("ac:name")
        if name != "code":
            self.unsupported.add(name or "unnamed macro")


def unsupported_markdown_macros(storage: str) -> list[str]:
    """Name the existing macros the Markdown conversion cannot recreate."""
    if "<ac:structured-macro" not in storage:
        return []
    collector = _MacroCollector()
    # A code block or comment can contain literal examples of macro markup.
    collector.feed(_LITERAL_STORAGE.sub("", storage))
    collector.close()
    return sorted(collector.unsupported)
