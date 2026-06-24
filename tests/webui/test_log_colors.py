"""Detail-page log viewer turns terminal ANSI/CSI sequences into safe HTML.

Color (SGR) codes -> <span style>; every other CSI sequence (cursor move,
erase-line, show/hide cursor, synchronized-output -- e.g. ollama's progress
bar) is stripped, not shown. Each line is HTML-escaped first, so untrusted
log text can never inject markup.
"""
from pathlib import Path

DETAIL = Path(__file__).resolve().parents[2] / "templates" / "pages" / "_job_detail.html"


def _html():
    return DETAIL.read_text(encoding="utf-8")


def test_log_viewer_has_esc_anchored_csi_matcher():
    html = _html()
    assert "ansiToHtml" in html
    # Matches any CSI sequence, anchored on the real ESC byte (so plain text like
    # "took [200ms]" is never mangled).
    assert r"/\x1b\[([0-?]*)[ -\/]*([@-~])/g" in html


def test_non_color_csi_is_stripped():
    html = _html()
    # cursor/erase/mode codes (do not end in 'm') are dropped, not rendered.
    assert "if (m[2] !== 'm') continue;" in html
    # stray C0 control bytes (leftover ESC / CR / BEL) are stripped too.
    assert r"/[\x00-\x08\x0b-\x1f\x7f]/g" in html


def test_both_render_paths_use_converter():
    html = _html()
    assert "node.innerHTML = this.ansiToHtml(text)" in html
    assert "arr.map((l) => this.ansiToHtml(l))" in html


def test_log_text_is_html_escaped_first():
    html = _html()
    assert ".replace(/&/g, '&amp;')" in html
    assert ".replace(/</g, '&lt;')" in html