"""Validate and atomically synchronize the versioned article bundle into PostgreSQL.

Run with: python -m app.blog_import [--check]
The API also runs the importer after migrations on startup.
"""
import argparse
import asyncio
import hashlib
import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from sqlalchemy import delete, func, select, text, update

from app.db import SessionLocal, engine
from app.models import BlogAsset, BlogPost

CONTENT_ROOT = Path(__file__).resolve().parents[1] / "content" / "blog"


@dataclass
class Article:
    slug: str
    metadata: dict
    files: dict[str, bytes]
    digest: str


class MediaReferences(HTMLParser):
    """Collect local media references plus the facts the content rules check."""

    def __init__(self):
        super().__init__()
        self.references: list[str] = []
        self.external: list[str] = []
        self.scripts: list[str] = []
        self.html_lang: str | None = None
        self.title: str | None = None
        self.description: str | None = None
        self.og_image: str | None = None
        self._in_title = False
        self._in_style = False

    def _resource(self, value: str):
        url = urlsplit(value)
        if url.scheme in {"http", "https"} or value.startswith("//"):
            self.external.append(value)
        else:
            self.references.append(value)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append("<script>")
        if tag == "html":
            self.html_lang = dict(attrs).get("lang")
        if tag == "title" and self.title is None:
            self._in_title, self.title = True, ""
        if tag == "style":
            self._in_style = True
        if tag == "meta":
            meta = dict(attrs)
            if (meta.get("name") or "").lower() == "description":
                self.description = meta.get("content")
            if (meta.get("property") or "").lower() == "og:image":
                self.og_image = meta.get("content")
        for key, value in attrs:
            if key.startswith("on"):
                self.scripts.append(f"{key}= attribute")
            if not value:
                continue
            if value.strip().lower().startswith("javascript:"):
                self.scripts.append(f"javascript: URL in {key}")
            elif key == "style":
                self._css(value)
            elif key in {"src", "poster"} or (tag == "link" and key == "href"):
                if not value.startswith("data:"):
                    self._resource(value)
            elif key == "srcset" and not value.startswith("data:"):
                for item in value.split(","):
                    if item.strip():
                        self._resource(item.strip().split()[0])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_style:
            self._css(data)

    def _css(self, css: str):
        # url(...) and @import inside styles load resources just like src attributes do.
        for match in re.finditer(r"""url\(\s*['"]?([^'")\s]+)|@import\s+['"]([^'"]+)""", css):
            value = match.group(1) or match.group(2)
            if not value.startswith(("data:", "#")):
                self._resource(value)


def check_article(slug: str, metadata: dict, html: bytes, files: dict[str, bytes]) -> None:
    """Publishing rules for index.html, so problems fail the release instead of reaching readers."""
    parser = MediaReferences()
    parser.feed(html.decode("utf-8"))
    problems = []
    if parser.html_lang != metadata["language"]:
        problems.append(f'<html lang> must be "{metadata["language"]}" (found {parser.html_lang!r})')
    if (parser.title or "").strip() != metadata["title"].strip():
        problems.append("<title> must match post.json title")
    if not (parser.description or "").strip():
        problems.append('<meta name="description"> is required')
    if parser.external:
        problems.append(f"external resources are not allowed (host them in the article folder): {', '.join(parser.external[:3])}")
    if parser.scripts:
        problems.append(f"scripts are not allowed: {', '.join(parser.scripts[:3])}")
    if parser.og_image and not urlsplit(parser.og_image).scheme and parser.og_image not in files:
        problems.append("og:image must refer to an existing article asset")
    if problems:
        raise ValueError(f"{slug}/index.html: " + "; ".join(problems))


def read_bundle(root: Path = CONTENT_ROOT) -> list[Article]:
    articles = []
    # Missing content is a packaging error, not an instruction to withdraw all posts.
    for directory in sorted(root.iterdir()):
        # "_template" and similar folders are examples, never published
        if directory.name.startswith((".", "_")):
            continue
        if directory.is_symlink() or not directory.is_dir() or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", directory.name
        ) or len(directory.name) > 160:
            raise ValueError(f"Invalid article directory: {directory.name}")
        metadata = json.loads((directory / "post.json").read_text(encoding="utf-8"))
        for field in ("title", "description", "language"):
            if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                raise ValueError(f"{directory.name}: {field} is required")
        if len(metadata["language"]) > 32 or type(metadata.get("draft")) is not bool:
            raise ValueError(f"{directory.name}: invalid language or draft")
        if "publishedAt" in metadata:
            value = metadata["publishedAt"]
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError(f"{directory.name}: publishedAt must be YYYY-MM-DD")
            date.fromisoformat(value)
        files = {}
        for file in sorted(directory.rglob("*")):
            relative = file.relative_to(directory)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if file.is_symlink():
                raise ValueError(f"{directory.name}: symlinks are not supported")
            if file.is_file() and relative.as_posix() != "post.json":
                files[relative.as_posix()] = file.read_bytes()
        if not metadata["draft"] and "index.html" not in files:
            raise ValueError(f"{directory.name}: index.html is required")
        if not metadata["draft"] and "publishedAt" not in metadata:
            raise ValueError(f"{directory.name}: publishedAt is required when draft is false")
        if "index.html" in files:
            check_article(directory.name, metadata, files["index.html"], files)
        cover = metadata.get("cover")
        if cover is not None and (not isinstance(cover, str) or cover not in files):
            raise ValueError(f"{directory.name}: cover must refer to an existing article asset")
        for name, data in files.items():
            if name.endswith(".html"):
                parser = MediaReferences()
                parser.feed(data.decode("utf-8"))
                for reference in parser.references:
                    url = urlsplit(reference)
                    if url.scheme or url.netloc or not url.path:
                        continue
                    # Keep original relative paths; fail a release rather than ship broken media.
                    candidate = PurePosixPath(name).parent / unquote(url.path)
                    if url.path.startswith("/") or ".." in candidate.parts or candidate.as_posix() not in files:
                        raise ValueError(f"{directory.name}/{name}: missing or non-local media: {reference}")
        digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode())
        for name, data in files.items():
            digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
        articles.append(Article(directory.name, metadata, files, digest.hexdigest()))
    return articles


async def import_bundle(root: Path = CONTENT_ROOT) -> int:
    articles = await asyncio.to_thread(read_bundle, root)
    changed = 0
    async with SessionLocal.begin() as session:
        # Concurrent API replicas must never expose a half-written bundle.
        await session.execute(text("SELECT pg_advisory_xact_lock(728193064)"))
        existing = {post.slug: post for post in (await session.scalars(select(BlogPost))).all()}
        for article in articles:
            meta = article.metadata
            post = existing.pop(article.slug, None)
            if post and post.bundle_hash == article.digest and post.draft == meta["draft"]:
                continue
            if post is None:
                post = BlogPost(slug=article.slug)
                session.add(post)
            post.title = meta["title"]
            post.description = meta["description"]
            post.language = meta["language"]
            post.published_at = date.fromisoformat(meta["publishedAt"]) if meta.get("publishedAt") else None
            post.draft = meta["draft"]
            post.cover = meta.get("cover")
            post.bundle_hash = article.digest
            post.updated_at = func.now()
            await session.flush()
            await session.execute(delete(BlogAsset).where(BlogAsset.post_slug == article.slug))
            session.add_all([
                BlogAsset(
                    post_slug=article.slug, path=name, data=data,
                    content_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                    sha256=hashlib.sha256(data).hexdigest(),
                )
                for name, data in article.files.items()
            ])
            changed += 1
        # Removing a source directory withdraws it; retained bytes remain in DB/backups.
        if existing:
            await session.execute(
                update(BlogPost).where(BlogPost.slug.in_(existing), BlogPost.draft.is_(False))
                .values(draft=True, updated_at=func.now())
            )
    return changed


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate content without connecting to DB")
    args = parser.parse_args()
    try:
        if args.check:
            print(f"Validated {len(read_bundle())} article(s).")
        else:
            print(f"Imported {await import_bundle()} changed article(s).")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
