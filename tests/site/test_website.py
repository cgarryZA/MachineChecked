"""Basic contract for the publicly deployed landing page.

These checks run without installing Lean, Node or a web browser. They do not
replace responsive visual and accessibility testing.
"""
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
WORKFLOW = ROOT / ".github/workflows/pages.yml"


class Inspect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.ids = set()
        self.hrefs = []
        self.images = []
        self.headings = []
        self.metadata = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a":
            self.hrefs.append(attrs.get("href", ""))
        if tag in ("img", "source"):
            self.images.append(attrs.get("src", attrs.get("srcset", "")))
        if tag == "meta":
            name = attrs.get("property", attrs.get("name"))
            if name:
                self.metadata[name] = attrs.get("content", "")
        if tag in ("h1", "h2", "h3"):
            self.headings.append(tag)


def test_homepage_has_a_clear_accessible_first_run_path():
    html = (SITE / "index.html").read_text(encoding="utf8")
    p = Inspect()
    p.feed(html)
    assert p.tags.count("main") == 1
    assert p.headings.count("h1") == 1
    assert {"main", "how", "start"} <= p.ids
    assert '#main' in p.hrefs  # keyboard skip link
    assert "/demo/" in p.hrefs
    assert "#start" in p.hrefs
    assert "machinechecked view" in html
    assert "A link is not a proof. A proof is not a review." in html
    assert "catalogue is planned" in html
    assert 'id="copy-command"' in html


def test_public_preview_and_discoverability_files():
    html = (SITE / "index.html").read_text(encoding="utf8")
    p = Inspect()
    p.feed(html)
    assert p.metadata["og:url"] == "https://machinechecked.org/"
    assert p.metadata["og:image"] == "https://machinechecked.org/preview-light.webp"
    assert p.metadata["twitter:card"] == "summary_large_image"
    for src in ("/preview-light.webp", "/preview-dark.webp"):
        assert src in p.images
        assert (SITE / src.lstrip("/")).exists()
    sitemap = ET.fromstring((SITE / "sitemap.xml").read_text())
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    urls = {e.text for e in sitemap.iter(f"{ns}loc")}
    assert {"https://machinechecked.org/", "https://machinechecked.org/demo/"} <= urls
    robots = (SITE / "robots.txt").read_text()
    assert "Sitemap: https://machinechecked.org/sitemap.xml" in robots
    assert (SITE / "llms.txt").exists()
    assert (SITE / "404.html").exists()
    assert "cp -R site/. public/" in WORKFLOW.read_text()
