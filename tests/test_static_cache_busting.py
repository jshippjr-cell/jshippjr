"""Static assets get a 7-day browser cache (Cache-Control: max-age=604800), so
every page that links site.css MUST use the same cache-busting ?v= query as
public_base.html — otherwise a browser that ever cached an old copy keeps serving
it for a week and new CSS silently never loads (this happened: /reel and /showreel
shipped with an unversioned link while public_base.html was on ?v=4/5).

The buster is now a single template global (``?v={{ asset_v }}``) so all pages
share ONE value by construction; this test still guards that no page drifts to a
different hardcoded version or drops the buster entirely.
"""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "src/chordential_oia/web/templates"

# Standalone pages that don't extend public_base.html but still load site.css
# directly — each of these must carry the SAME version as public_base.html.
STANDALONE_PUBLIC_PAGES = [
    TEMPLATES / "public" / "showreel.html",
]


def _site_css_version(html: str) -> str:
    # Captures a literal version (?v=22) OR the shared template global (?v={{ asset_v }})
    # — either way, all pages must resolve to the SAME token.
    m = re.search(r'href="/static/public/site\.css(?:\?v=([^"]+))?"', html)
    assert m, "no site.css <link> found"
    return m.group(1) or ""


def test_standalone_pages_match_public_base_css_version():
    base_version = _site_css_version((TEMPLATES / "public_base.html").read_text())
    assert base_version, "public_base.html's site.css link has no ?v= cache-buster"
    for page in STANDALONE_PUBLIC_PAGES:
        version = _site_css_version(page.read_text())
        assert version == base_version, (
            f"{page.name} links site.css?v={version!r} but public_base.html is "
            f"?v={base_version!r} — a browser with the old version cached (7-day "
            f"max-age) will never see this page's CSS additions"
        )


# Every <script src="/static/public/*.js"> must carry its own ?v= — this bit for
# real: reel-carousel.js shipped unversioned through several rewrites (drag
# engine, then the inline audio player), so a browser that had ever cached the
# very first copy kept serving it for the full 7-day max-age — cards silently
# navigated away, never popped forward, and never showed the docked player,
# because the running JS was months of iteration behind the HTML it loaded.
def test_every_local_js_script_tag_has_a_cache_buster():
    js_tag_re = re.compile(r'<script src="(/static/public/[^"]+\.js)(\?v=(\w+))?">')
    missing = []
    for page in TEMPLATES.rglob("*.html"):
        for path, _, version in js_tag_re.findall(page.read_text()):
            if not version:
                missing.append(f"{page.relative_to(TEMPLATES)} -> {path}")
    assert not missing, f"unversioned <script> tags (never cache-bustable): {missing}"
