import json
import os
import re
import shutil
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import blog_import, deps
from app.blog_import import CONTENT_ROOT, read_bundle
from app.blog_render import NAVIGATION, render_article
from app.config import get_settings
from app.main import app
from app.models import BlogAsset, BlogPost


FIXTURE = ("relay-day", "_template")


def _copy_fixture(root: Path) -> None:
    """这些测试验证导入机制，只用 relay-day 这一篇做样本；新增文章不应该让它们失败。"""
    root.mkdir(parents=True)
    for name in FIXTURE:
        shutil.copytree(CONTENT_ROOT / name, root / name)


def test_every_published_article_is_valid():
    """真实内容目录里的每一篇都要通过发布校验（新文章由这条覆盖）。"""
    slugs = [a.slug for a in read_bundle(CONTENT_ROOT)]
    assert "relay-day" in slugs and len(slugs) == len(set(slugs))


def test_bundle_preserves_original_bytes_and_validates_media(tmp_path):
    root = tmp_path / "blog"
    _copy_fixture(root)
    article = read_bundle(root)[0]
    assert article.files["index.html"] == (root / "relay-day/index.html").read_bytes()
    assert len(article.files) == 10  # HTML + eight JPGs + MP4
    (root / "relay-day/img/board.jpg").unlink()
    with pytest.raises(ValueError, match="missing or non-local media"):
        read_bundle(root)


def test_og_image_becomes_absolute_and_the_rest_is_untouched():
    page = b'<html><head><meta property="og:image" content="img/cover.jpg"></head><body><p>x</p></body></html>'
    rendered = render_article(page, "https://relay.example/blog/post/")
    assert b'content="https://relay.example/blog/post/img/cover.jpg"' in rendered
    assert rendered.replace(NAVIGATION, b"", 1) == page.replace(b"img/cover.jpg", b"https://relay.example/blog/post/img/cover.jpg")
    assert render_article(page) == page.replace(b"<body>", b"<body>" + NAVIGATION)


def test_template_and_hidden_folders_are_not_published(tmp_path):
    root = tmp_path / "blog"
    _copy_fixture(root)
    assert [a.slug for a in read_bundle(root)] == ["relay-day"]
    # The template itself must pass the rules, so a copy starts from a valid article.
    shutil.copytree(root / "_template", root / "new-post")
    assert "new-post" in [a.slug for a in read_bundle(root)]


@pytest.mark.parametrize(("old", "new", "error"), [
    ('<html lang="zh-CN">', "<html>", "<html lang>"),
    ("<title>邮件、审批、群消息，每一件事都有人跟进</title>", "<title>Relay 宣传页</title>", "<title> must match"),
    ('<meta name="description"', '<meta name="keywords"', "description"),
    ("</head>", '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X"></head>', "external resources"),
    ("</head>", "<style>@import url(//cdn.example.com/a.css);</style></head>", "external resources"),
    ("</head>", "<style>body{background:url('https://x.example/b.png')}</style></head>", "external resources"),
    ("</body>", "<script>alert(1)</script></body>", "scripts are not allowed"),
    ("<footer>", '<footer onclick="steal()">', "scripts are not allowed"),
    ("<footer>", '<a href="javascript:void(0)">x</a><footer>', "scripts are not allowed"),
    ('content="img/cover.jpg"', 'content="img/missing.jpg"', "og:image"),
])
def test_content_rules_block_release(tmp_path, old, new, error):
    root = tmp_path / "blog"
    _copy_fixture(root)
    page = root / "relay-day/index.html"
    html = page.read_text(encoding="utf-8")
    assert old in html
    page.write_text(html.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(error)):
        read_bundle(root)


def test_published_articles_need_a_date_but_drafts_do_not(tmp_path):
    root = tmp_path / "blog"
    _copy_fixture(root)
    metadata = root / "relay-day/post.json"
    data = json.loads(metadata.read_text())
    del data["publishedAt"]
    metadata.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="publishedAt is required"):
        read_bundle(root)
    metadata.write_text(json.dumps({**data, "draft": True}))
    assert read_bundle(root)[0].metadata["draft"] is True
    # External links people click are fine; only resources the page loads are restricted.
    page = root / "relay-day/index.html"
    page.write_text(page.read_text(encoding="utf-8").replace("<footer>", '<a href="https://example.com">x</a><footer>', 1), encoding="utf-8")
    read_bundle(root)


@pytest_asyncio.fixture
async def blog_db(monkeypatch):
    if not os.getenv("RUN_DB_TESTS"):
        pytest.skip("Requires isolated test database and RUN_DB_TESTS=1")
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(blog_import, "SessionLocal", factory)
    async def get_session():
        async with factory() as session:
            yield session
    app.dependency_overrides[deps.get_session] = get_session
    async with factory.begin() as session:
        await session.execute(delete(BlogPost))
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(deps.get_session, None)
        async with factory.begin() as session:
            await session.execute(delete(BlogPost))
        await engine.dispose()


async def test_import_and_serving_survive_missing_source_files(blog_db, tmp_path):
    root = tmp_path / "blog"
    _copy_fixture(root)
    originals = read_bundle(root)[0].files
    assert await blog_import.import_bundle(root) == 1
    async with blog_db() as session:
        timestamp = (await session.get(BlogPost, "relay-day")).updated_at
    assert await blog_import.import_bundle(root) == 0
    async with blog_db() as session:
        assert (await session.get(BlogPost, "relay-day")).updated_at == timestamp
        assert await session.scalar(select(func.count()).select_from(BlogAsset)) == 10
    shutil.rmtree(root)  # The live endpoint must not depend on files in the frontend/image.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
        response = await client.get("/api/blog")
        assert response.status_code == 200
        assert response.json()[0]["cover"] == "/blog/relay-day/img/cover.jpg"
        for name, data in originals.items():
            url = f"/blog/relay-day/{name}"
            response = await client.get(url)
            assert response.status_code == 200
            if name == "index.html":
                assert response.content.count(NAVIGATION) == 1
                # Only the navigation and the absolute og:image differ from the stored page.
                assert b'content="http://localhost:5173/blog/relay-day/img/cover.jpg"' in response.content
                assert render_article(data, "http://localhost:5173/blog/relay-day/") == response.content
            else:
                assert response.content == data
            if name.endswith(".jpg"):
                assert response.headers["content-type"] == "image/jpeg"
            assert "script-src 'self'" in response.headers["content-security-policy"]
            etag = response.headers["etag"]
            assert (await client.get(url, headers={"If-None-Match": etag})).status_code == 304
            head = await client.head(url)
            assert head.content == b"" and int(head.headers["content-length"]) == len(response.content)
        assert (await client.get("/blog/relay-day/")).content == render_article(originals["index.html"], "http://localhost:5173/blog/relay-day/")
        redirect = await client.get("/blog/relay-day?ref=test")
        assert redirect.headers["location"] == "/blog/relay-day/?ref=test"
        for name in ("missing.jpg", "post.json", "../post.json"):
            assert (await client.get(f"/blog/relay-day/{name}")).status_code == 404
        video_url = "/blog/relay-day/relay-promo.mp4"
        video = originals["relay-promo.mp4"]
        for value, expected in [("bytes=0-99", video[:100]), ("bytes=-100", video[-100:]), ("bytes=100-", video[100:])]:
            response = await client.get(video_url, headers={"Range": value})
            assert response.status_code == 206 and response.content == expected
            assert response.headers["content-range"].endswith(f"/{len(video)}")
        for invalid in ("bytes=999999999-", "bytes=8-4", "bytes=-0", "bytes=-", "bytes=1-2,4-5"):
            assert (await client.get(video_url, headers={"Range": invalid})).status_code == 416
        assert (await client.get(video_url, headers={"Range": "bytes=0-99", "If-Range": '"old"'})).content == video


async def test_updates_drafts_withdrawal_and_validation_are_atomic(blog_db, tmp_path):
    root = tmp_path / "blog"
    _copy_fixture(root)
    metadata = root / "relay-day/post.json"
    original = json.loads(metadata.read_text())
    await blog_import.import_bundle(root)
    # An invalid release must leave the previous public document intact.
    metadata.write_text(json.dumps({**original, "cover": "missing.jpg"}))
    with pytest.raises(ValueError):
        await blog_import.import_bundle(root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
        assert (await client.get("/blog/relay-day/")).status_code == 200
        metadata.write_text(json.dumps({**original, "draft": True}))
        await blog_import.import_bundle(root)
        assert (await client.get("/api/blog")).json() == []
        assert (await client.get("/blog/relay-day/")).status_code == 404
        assert (await client.get("/blog/relay-day/img/cover.jpg")).status_code == 404
        metadata.write_text(json.dumps(original))
        # Removed assets are not left behind after an updated import.
        (root / "relay-day/extra.txt").write_text("temporary")
        await blog_import.import_bundle(root)
        assert (await client.get("/blog/relay-day/extra.txt")).text == "temporary"
        (root / "relay-day/extra.txt").unlink()
        await blog_import.import_bundle(root)
        assert (await client.get("/blog/relay-day/extra.txt")).status_code == 404
        shutil.rmtree(root / "relay-day")
        await blog_import.import_bundle(root)
        assert (await client.get("/api/blog")).json() == []
        # Returning an unchanged directory republishes a withdrawn article.
        shutil.copytree(CONTENT_ROOT / "relay-day", root / "relay-day")
        await blog_import.import_bundle(root)
        assert (await client.get("/blog/relay-day/")).status_code == 200
