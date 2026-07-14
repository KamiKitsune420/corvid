from __future__ import annotations

from corvid.htmlsanitize import html_to_text, sanitize_html


def test_strips_script_and_contents() -> None:
    result = sanitize_html("<p>hi</p><script>alert('x')</script>")
    assert "alert" not in result.html
    assert "<script" not in result.html
    assert "hi" in result.html


def test_strips_event_handlers_and_style() -> None:
    result = sanitize_html('<a href="https://x" onclick="evil()" style="x">link</a>')
    assert "onclick" not in result.html
    assert "style" not in result.html
    assert 'href="https://x"' in result.html


def test_rejects_javascript_url() -> None:
    result = sanitize_html('<a href="javascript:evil()">x</a>')
    assert "javascript" not in result.html


def test_blocks_remote_images_by_default() -> None:
    result = sanitize_html('<img src="http://tracker.example/pixel.gif">')
    assert result.remote_blocked is True
    assert "tracker.example" not in result.html


def test_allows_remote_images_when_unblocked() -> None:
    result = sanitize_html('<img src="https://ok/i.png">', block_remote=False)
    assert result.remote_blocked is False
    assert "https://ok/i.png" in result.html


def test_disallowed_tag_dropped_but_text_kept() -> None:
    result = sanitize_html("<marquee>keep me</marquee>")
    assert "<marquee" not in result.html
    assert "keep me" in result.html


def test_html_to_text() -> None:
    assert html_to_text("<p>one</p><p>two</p>").replace("\n", " ").split() == ["one", "two"]
    assert "script" not in html_to_text("<script>bad</script>hello")
