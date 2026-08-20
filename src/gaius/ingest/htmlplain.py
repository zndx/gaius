"""Inbound HTML → plain/markdown text before CLT or MaxSim.

RSS ``summary``/``content`` is often HTML. Regex tag-strips leave entities
(``&apos;``) and CLT then fires HTML-tag features on “markdown” windows.
"""

from __future__ import annotations

import html
import re

_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def to_plain_text(raw: str) -> str:
    """Unescape entities; if HTML tags remain, drop them via the parser."""
    text = html.unescape(raw or "")
    if _TAG.search(text):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text("\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
