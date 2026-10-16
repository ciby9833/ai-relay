"""文档与知识库搜索：用用户本人的权限搜，搜到的都是他能看的。"""
import html

from app.feishu.client import FeishuClient
from app.models import User


async def search(feishu: FeishuClient, user: User, query: str, limit: int = 8) -> list[dict]:
    return (await search_page(feishu, user, query, limit))["items"]


async def search_page(feishu: FeishuClient, user: User, query: str, limit: int = 8, page_token: str | None = None) -> dict:
    data = await feishu.user_api(
        user, "POST", "/search/v2/doc_wiki/search",
        json={"query": query, "page_size": limit, "doc_filter": {}, "wiki_filter": {},
              **({"page_token": page_token} if page_token else {})},
    )
    results = []
    for unit in data.get("res_units") or []:
        meta = unit.get("result_meta") or {}
        results.append(
            {
                "title": html.unescape((unit.get("title_highlighted") or meta.get("title") or "").replace("<h>", "").replace("</h>", "")),
                "summary": html.unescape((unit.get("summary_highlighted") or "").replace("<h>", "").replace("</h>", ""))[:300],
                "url": meta.get("url"),
                "type": unit.get("entity_type") or meta.get("doc_types"),
                "updated": meta.get("update_time_iso") or meta.get("update_time"),
            }
        )
    return {"items": results, "has_more": data.get("has_more", False), "page_token": data.get("page_token"),
            "total": data.get("total"), "notice": data.get("notice")}
