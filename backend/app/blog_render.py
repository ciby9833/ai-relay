"""Add shared site navigation without changing the stored article or its styles."""
import re
from urllib.parse import urljoin

NAVIGATION = (
    b'<relay-blog-navigation full-bleed style="display:block;min-height:89px">'
    b'</relay-blog-navigation>'
    b'<relay-blog-toc></relay-blog-toc>'
    # ?v= only needs to change if browsers might still hold an old copy; Nginx now sends no-cache for this file.
    b'<script src="/blog-navigation.js?v=2" defer></script>'
)
OG_IMAGE = re.compile(
    rb'(<meta\b[^>]*\bproperty=["\']og:image["\'][^>]*\bcontent=["\'])([^"\']+)(["\'])', re.IGNORECASE
)


def render_article(original: bytes, base_url: str | None = None) -> bytes:
    """base_url is the article's public folder URL; link previews (Feishu etc.) need an absolute og:image."""
    if base_url:
        original = OG_IMAGE.sub(lambda m: m[1] + urljoin(base_url, m[2].decode()).encode() + m[3], original)
    body = re.search(rb"<body\b[^>]*>", original, flags=re.IGNORECASE)
    if body:
        return original[:body.end()] + NAVIGATION + original[body.end():]
    return NAVIGATION + original
