"""Detail-page log viewer colorizes terminal ANSI (SGR) codes into safe HTML.

TEI / inference servers emit ANSI color codes (e.g. ``\\x1b[32m INFO \\x1b[0m``). The
log panel converts them to ``<span style>`` client-side — HTML-escaping each line
first, so untrusted log text can never inject markup. This guards the wiring:
the converter exists, both render paths use it, and escaping is in place.
"""
from pathlib import Path

DETAIL = Path(__file__).resolve().parents[2] / "templates" / "pages" / "_job_detail.html"


def test_log_viewer_has_esc_anchored_converter():
    html = DETAIL.read_text(encoding="utf-8")
    assert "ansiToHtml" in html
    # Must anchor on the real ESC byte, not a bare [..m that would mangle plain
    # log text like "took [200ms]".
    assert r"/\x1b\[([0-9;]*)m/g" in html


def test_both_render_paths_use_converter():
    html = DETAIL.read_text(encoding="utf-8")
    assert "node.innerHTML = this.ansiToHtml(text)" in html          # live append
    assert "arr.map((l) => this.ansiToHtml(l))" in html              # full re-render


def test_log_text_is_html_escaped_first():
    html = DETAIL.read_text(encoding="utf-8")
    # XSS safety: log text is escaped before being wrapped in spans.
    assert ".replace(/&/g, '&amp;')" in html
    assert ".replace(/</g, '&lt;')" in html
