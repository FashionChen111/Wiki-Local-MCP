"""Convert Confluence storage XHTML to Markdown."""

import re
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter


_CODE_LANGUAGE_ATTR = "data-confluence-code-language"


class _StorageMarkdownConverter(MarkdownConverter):
    def convert_pre(self, el: Tag, text: str, *args, **kwargs) -> str:
        language = el.get(_CODE_LANGUAGE_ATTR)
        if not isinstance(language, str):
            return super().convert_pre(el, text, *args, **kwargs)
        if not re.fullmatch(r"[\w#.+-]+", language):
            language = ""
        code = el.get_text()
        longest = max((len(run) for run in re.findall(r"`+", code)), default=0)
        fence = "`" * max(3, longest + 1)
        if not code.endswith("\n"):
            code += "\n"
        return f"\n\n{fence}{language}\n{code}{fence}\n\n"


def storage_to_markdown(storage_xhtml: str) -> str:
    """Convert the storage representation to readable Markdown."""
    soup = BeautifulSoup(storage_xhtml, "html.parser")
    for macro in soup.find_all("ac:structured-macro", attrs={"ac:name": "code"}):
        body = macro.find("ac:plain-text-body", recursive=False)
        if body is None:
            continue
        language = macro.find("ac:parameter", attrs={"ac:name": "language"}, recursive=False)
        pre = soup.new_tag("pre")
        pre[_CODE_LANGUAGE_ATTR] = language.get_text(strip=True) if language is not None else ""
        pre.string = body.get_text()
        macro.replace_with(pre)

    for image in soup.find_all("ac:image"):
        attachment = image.find("ri:attachment")
        external = image.find("ri:url")
        if attachment is not None and attachment.get("ri:filename") and attachment.find() is None:
            src = "attachment:" + quote(attachment["ri:filename"], safe="")
        elif external is not None and external.get("ri:value"):
            src = external["ri:value"]
        else:
            continue
        replacement = soup.new_tag("img", src=src, alt=image.get("ac:alt", ""))
        if image.get("ac:title"):
            replacement["title"] = image["ac:title"]
        image.replace_with(replacement)
    return _StorageMarkdownConverter(heading_style="ATX", bullets="-").convert_soup(soup).strip()
