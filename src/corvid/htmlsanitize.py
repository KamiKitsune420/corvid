"""Allowlist HTML sanitizer for safely displaying email bodies.

Email HTML is hostile input. This sanitizer:

* keeps only an allowlist of structural/formatting tags and attributes;
* drops ``<script>``/``<style>``/``<iframe>``/``<object>`` etc. *and their
  contents*;
* strips all event handlers (``on*``) and ``style`` attributes;
* permits only safe URL schemes (http/https/mailto) on links;
* blocks remote content by default - image ``src`` to remote hosts is removed
  (and reported), defeating tracking pixels, until the user opts in.

It produces a fragment intended to be rendered by ``wx.html.HtmlWindow``, which
executes no JavaScript and does not load remote resources on its own - so this
is defense in depth, not the only line of defense.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser

_ALLOWED_TAGS = {
    "p", "br", "div", "span", "a", "b", "i", "u", "em", "strong", "small",
    "blockquote", "pre", "code", "hr", "sub", "sup", "font", "center",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "img",
}

# Tags whose entire contents must be discarded.
_SKIP_TAGS = {"script", "style", "head", "title", "noscript", "iframe", "object", "embed"}

_VOID_TAGS = {"br", "hr", "img"}

_ALLOWED_ATTRS: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan", "align", "valign"},
    "th": {"colspan", "rowspan", "align", "valign"},
    "font": {"color", "face", "size"},
    "table": {"border", "cellpadding", "cellspacing", "width"},
}

_SAFE_URL_SCHEMES = {"http", "https", "mailto"}


@dataclass(slots=True)
class SanitizeResult:
    html: str
    remote_blocked: bool = False


def _scheme_ok(url: str) -> bool:
    stripped = url.strip().lower()
    if ":" not in stripped:
        return True  # relative / anchor / fragment
    scheme = stripped.split(":", 1)[0]
    # Reject "javascript", "data", "vbscript", "file", etc.
    if any(c in scheme for c in "/?#"):
        return True  # the ':' belonged to a path, not a scheme
    return scheme in _SAFE_URL_SCHEMES


class _Sanitizer(HTMLParser):
    def __init__(self, *, block_remote: bool) -> None:
        super().__init__(convert_charrefs=True)
        self._block_remote = block_remote
        self._skip_depth = 0
        self.parts: list[str] = []
        self.remote_blocked = False

    # -- helpers ------------------------------------------------------------
    def _clean_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        allowed = _ALLOWED_ATTRS.get(tag, set())
        rendered: list[str] = []
        for name, value in attrs:
            name = name.lower()
            if name.startswith("on") or name == "style" or name not in allowed:
                continue
            value = value or ""
            if name in ("href", "src") and not _scheme_ok(value):
                continue
            if tag == "img" and name == "src":
                lowered = value.strip().lower()
                is_remote = lowered.startswith(("http://", "https://"))
                if self._block_remote and is_remote:
                    self.remote_blocked = True
                    continue
            rendered.append(f'{name}="{escape(value, quote=True)}"')
        return (" " + " ".join(rendered)) if rendered else ""

    # -- parser callbacks ---------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth or tag not in _ALLOWED_TAGS:
            return
        self.parts.append(f"<{tag}{self._clean_attrs(tag, attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth or tag not in _ALLOWED_TAGS:
            return
        self.parts.append(f"<{tag}{self._clean_attrs(tag, attrs)}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(escape(data))


def sanitize_html(html: str, *, block_remote: bool = True) -> SanitizeResult:
    """Return sanitized HTML plus whether remote content was blocked."""
    parser = _Sanitizer(block_remote=block_remote)
    parser.feed(html)
    parser.close()
    return SanitizeResult(html="".join(parser.parts), remote_blocked=parser.remote_blocked)


def html_to_text(html: str) -> str:
    """Crude HTML-to-text for plain rendering of HTML-only messages."""

    class _Stripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.text: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in _SKIP_TAGS:
                self._skip += 1
            elif tag in ("br", "p", "div", "tr", "li"):
                self.text.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in _SKIP_TAGS and self._skip:
                self._skip -= 1

        def handle_data(self, data: str) -> None:
            if not self._skip:
                self.text.append(data)

    stripper = _Stripper()
    stripper.feed(html)
    stripper.close()
    return "".join(stripper.text).strip()
