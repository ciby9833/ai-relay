import re
import hashlib
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import SessionDep
from app.blog_render import NAVIGATION, render_article
from app.models import BlogAsset, BlogPost

router = APIRouter()


@router.get("/api/blog")
async def list_posts(session: SessionDep):
    posts = (await session.scalars(
        select(BlogPost).where(BlogPost.draft.is_(False))
        .order_by(BlogPost.published_at.desc().nulls_last(), BlogPost.slug)
    )).all()
    return JSONResponse([
        {
            "slug": post.slug, "title": post.title, "description": post.description,
            "language": post.language,
            "publishedAt": post.published_at.isoformat() if post.published_at else None,
            "href": f"/blog/{post.slug}/",
            "cover": f"/blog/{post.slug}/{quote(post.cover)}" if post.cover else None,
        } for post in posts
    ], headers={"Cache-Control": "no-store"})


@router.api_route("/blog/{slug}", methods=["GET", "HEAD"])
async def article_redirect(slug: str, request: Request, session: SessionDep):
    exists = await session.scalar(
        select(BlogPost.slug).where(BlogPost.slug == slug, BlogPost.draft.is_(False))
    )
    if exists is None:
        raise HTTPException(404, "Article not found", headers={"Cache-Control": "no-store"})
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/blog/{quote(slug, safe='')}/{query}", status_code=308)


# Articles share the app's origin (and its login cookie), so only same-origin scripts may run:
# that covers the shared navigation, and nothing an article bundle could add inline or from a CDN.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; media-src 'self'; font-src 'self' data:; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
)
NAVIGATION_VERSION = hashlib.sha256(NAVIGATION).hexdigest()


@router.api_route("/blog/{slug}/{asset_path:path}", methods=["GET", "HEAD"])
async def article_asset(slug: str, asset_path: str, request: Request, session: SessionDep):
    asset_path = asset_path or "index.html"
    where = (BlogAsset.post_slug == slug, BlogAsset.path == asset_path)
    # Metadata first: a 304, a HEAD or a byte range must not pull a whole video out of Postgres.
    row = (await session.execute(
        select(BlogAsset.content_type, BlogAsset.sha256, func.length(BlogAsset.data))
        .join(BlogPost, BlogPost.slug == BlogAsset.post_slug)
        .where(*where, BlogPost.draft.is_(False))
    )).one_or_none()
    if row is None:
        raise HTTPException(404, "Article or file not found", headers={"Cache-Control": "no-store", "Content-Security-Policy": CSP})
    content_type, digest, size = row
    rendered = None
    if asset_path == "index.html":
        # The served page is the stored page plus the navigation and an absolute og:image, so the tag covers all three.
        # FRONTEND_URL is the public https origin; behind the WAF and proxies request.base_url says http.
        base_url = f"{get_settings().frontend_url.rstrip('/')}/blog/{quote(slug, safe='')}/"
        digest = hashlib.sha256(f"{digest}:{NAVIGATION_VERSION}:{base_url}".encode()).hexdigest()
        rendered = render_article(await session.scalar(select(BlogAsset.data).where(*where)), base_url)
        size = len(rendered)
    etag = f'"{digest}"'
    headers = {
        "ETag": etag, "Cache-Control": "public, max-age=0, must-revalidate",
        "Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": CSP,
    }
    if any(tag.strip().removeprefix("W/") in {etag, "*"} for tag in request.headers.get("if-none-match", "").split(",")):
        return Response(status_code=304, headers=headers)
    status, start, end = 200, 0, size - 1
    byte_range = request.headers.get("range") if request.method == "GET" else None
    if byte_range and request.headers.get("if-range", etag) == etag:
        match = re.fullmatch(r"bytes=(\d{0,20})-(\d{0,20})", byte_range)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        first, last = match.groups()
        start = int(first) if first else max(0, size - int(last))
        end = min(int(last), size - 1) if first and last else size - 1
        if start > end or start >= size or (not first and int(last) == 0):
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        status = 206
    headers["Content-Length"] = str(end - start + 1 if size else 0)
    if request.method == "HEAD":
        data = b""
    elif rendered is not None:
        data = rendered[start:end + 1]
    elif status == 206:
        # Postgres substring on bytea is 1-based.
        data = await session.scalar(select(func.substring(BlogAsset.data, start + 1, end - start + 1)).where(*where))
    else:
        data = await session.scalar(select(BlogAsset.data).where(*where))
    return Response(content=data, status_code=status, media_type=content_type, headers=headers)
