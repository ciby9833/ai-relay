"""只读验收：只输出计数、scope 和错误，不输出正文、资源 token 或凭证。

docker compose run --rm --no-deps api python -m scripts.audit_feishu
多用户环境必须传 --user-id；可传 --doc-url 验收指定的云文档/表格/画板。
"""
import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime
import json
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.feishu.client import FeishuClient, FeishuError
from app.models import User
from app.sources import approval, cloud, docs, mail


async def main(args):
    report = {"checked_at": datetime.now(UTC).isoformat(), "mode": "read_only", "checks": {}}
    async with httpx.AsyncClient(timeout=30) as http, SessionLocal() as session:
        users = (await session.execute(select(User))).scalars().all()
        selected = [u for u in users if not args.user_id or str(u.id) == args.user_id]
        if len(selected) != 1:
            raise SystemExit("请用 --user-id 指定一位用户（未选择或存在多位用户）")
        user, feishu = selected[0], FeishuClient(get_settings(), http)

        async def check(name, fn, summarize=lambda x: {"response_keys": list(x)}):
            try:
                data = await fn()
                report["checks"][name] = {"ok": True, **summarize(data)}
                return data
            except (FeishuError, httpx.HTTPError) as exc:
                report["checks"][name] = {"ok": False, "code": getattr(exc, "code", None), "error": str(exc)[:2000]}
                return None

        prefixes = ("approval:", "calendar:", "drive:", "space:", "wiki:", "docx:", "docs:", "sheets:", "bitable:", "board:", "search:docs")
        await check("app_scopes", lambda: feishu.tenant_api("GET", "/application/v6/scopes"),
            lambda d: {"scopes": [s for s in d.get("scopes", []) if s.get("scope_name", "").startswith(prefixes)]})
        report["user_scopes"] = [s for s in (user.feishu_scopes or "").split() if s.startswith(prefixes)]
        for category in ("pending", "done", "initiated", "cc"):
            await check("approval_" + category, lambda: approval.query_tasks(feishu, user, category),
                lambda rows: {"count": len(rows), "statuses": dict(Counter(str(r.get("process_status")) for r in rows))})
        for folder in mail.FOLDERS:
            await check("mail_" + folder, lambda: mail.list_folder(feishu, user, folder, 2),
                lambda rows: {"sample_count": len(rows), "full_mailbox": False})
        for name in ("get_drive_root", "list_drive_files", "list_wiki_spaces", "list_feishu_calendars"):
            await check(name, lambda: cloud.call(feishu, user, name, {}),
                lambda d: {"response_keys": list(d), "sample_count": len(d.get("items", d.get("files", d.get("calendar_list", [])))), "has_more": d.get("has_more")})
        page = await check("search_docs", lambda: docs.search_page(feishu, user, args.query),
            lambda d: {"sample_count": len(d["items"]), "has_more": d["has_more"]})
        urls, seen = ([args.doc_url] if args.doc_url else []), set()
        for row in (page or {}).get("items", []):
            url = row.get("url") or ""
            kind = urlparse(url).path.split("/")[1:2]
            if kind and kind[0] in ("docx", "wiki", "base", "sheets", "board") and kind[0] not in seen:
                seen.add(kind[0])
                urls.append(url)
        for i, url in enumerate(urls):
            await check(f"read_resource_{i + 1}", lambda: cloud.read_url(feishu, user, url),
                lambda d: {"kind": d.get("resource_type", "docx"), "content_chars": len(d.get("content", "")), "response_keys": list(d)})
        report["write_checks"] = "未执行真实业务写入；使用自动化模拟测试验证请求与确认流程"
        print(json.dumps(report, ensure_ascii=False, indent=2))
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id")
    parser.add_argument("--doc-url")
    parser.add_argument("--query", default="项目")
    asyncio.run(main(parser.parse_args()))
