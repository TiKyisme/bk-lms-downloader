from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"


def test_static_website_has_vietnamese_page_and_required_product_links():
    page = (WEBSITE / "index.html").read_text(encoding="utf-8")

    assert '<html lang="vi">' in page
    assert "https://apps.microsoft.com/detail/9N1TTL7WPJT0" in page
    assert "https://github.com/TiKyisme/bk-lms-downloader" in page
    assert "localhost" not in page
    assert "google-analytics" not in page.lower()
    assert "bk-lms-demo.mp4" in page
    assert "AI Study Pack" in page


def test_static_website_assets_and_pages_workflow_exist():
    for path in (
        WEBSITE / "styles.css",
        WEBSITE / "script.js",
        WEBSITE / "robots.txt",
        WEBSITE / "sitemap.xml",
        WEBSITE / "assets" / "app-window.png",
        WEBSITE / "assets" / "brand.png",
        ROOT / ".github" / "workflows" / "pages.yml",
    ):
        assert path.is_file(), path
