"""同事名册：私聊、群聊里出现过的人（被@的、发言的）、Relay 用户、按邮箱从通讯录查到的人。

用来把“Andrew（陈春华）”这样的名字对应到飞书身份，以便发消息、建任务、约会。
"""

import re
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.feishu.client import FeishuClient, FeishuError
from app.models import Person, User

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# “Andrew（陈春华）”“Jeffrey (郭敬贤)”：括号里外都可以用来找人
_PARTS = re.compile(r"[（(]([^）)]+)[）)]")
_CJK = re.compile(r"[\u4e00-\u9fff]{2,}")


class Ambiguous(Exception):
    """同名的人不止一个，需要用户指明。"""

    def __init__(self, query: str, candidates: list[dict]):
        super().__init__(query)
        self.query, self.candidates = query, candidates


async def remember(session: AsyncSession, people: list[tuple[str | None, str | None, str]]) -> None:
    """记下 (open_id, 名字, 来源)；同一个人以最新的名字为准。"""
    rows = {open_id: (name, source) for open_id, name, source in people if open_id and name}
    for open_id, (name, source) in rows.items():
        await session.execute(
            insert(Person).values(open_id=open_id, name=name[:255], source=source, updated_at=datetime.now(UTC))
            .on_conflict_do_update(index_elements=["open_id"], set_={"name": name[:255], "updated_at": datetime.now(UTC)})
        )


def _variants(query: str) -> list[str]:
    """一个人名的各种写法，越能唯一确定一个人的越靠前：中文名、括号里的名字、完整写法、英文名。"""
    query = query.strip().lstrip("@").strip()
    inner = [p.strip() for p in _PARTS.findall(query)]
    outer = _PARTS.sub("", query).strip()
    chinese = _CJK.findall(query)
    latin = _CJK.sub("", outer).strip(" ·-")
    variants = chinese + inner + [query, outer, latin]
    return [v for v in dict.fromkeys(variants) if len(v) >= 2]


async def _search_feishu(feishu: FeishuClient, user: User, query: str) -> list[dict]:
    """以用户本人的身份在飞书里搜同事（和他在飞书里搜人看到的一样，不受应用通讯录范围限制）。"""
    data = await feishu.user_api(user, "GET", "/search/v1/user", params={"query": query, "page_size": 10})
    return [{"name": u["name"], "open_id": u["open_id"]} for u in data.get("users") or [] if u.get("open_id")]


async def find(
    session: AsyncSession, feishu: FeishuClient, query: str, limit: int = 5, user: User | None = None
) -> list[dict]:
    """按名字或企业邮箱找同事。先查名册，再以用户身份搜飞书；同名多人时抛出 Ambiguous。"""
    query = query.strip().lstrip("@")
    if EMAIL.fullmatch(query):
        try:
            data = await feishu.tenant_api(
                "POST", "/contact/v3/users/batch_get_id", params={"user_id_type": "open_id"}, json={"emails": [query]}
            )
        except FeishuError:
            return []
        found = [{"name": query, "open_id": u["user_id"], "source": "通讯录"} for u in data.get("user_list") or [] if u.get("user_id")]
        await remember(session, [(p["open_id"], await feishu.user_name(p["open_id"]) or query, "contact") for p in found])
        return found
    variants = _variants(query)
    if not variants:
        return []
    # 写了中文名或括号里的名字时，单独的英文名太弱（公司里可能有好几个 Andrew），不拿来在名册里直接认人
    strong = [v for v in variants if _CJK.search(v) or v == query.strip()] or variants
    # 1. 名册里名字完全一致的
    exact = (await session.execute(select(Person).where(Person.name.in_(strong)).limit(limit))).scalars().all()
    if len({p.open_id for p in exact}) == 1:
        return [{"name": exact[0].name, "open_id": exact[0].open_id, "source": "名册"}]
    # 2. 以用户身份搜飞书：先用最能确定人的写法（中文名）搜
    if user is not None:
        seen: dict[str, dict] = {}
        for variant in variants:
            try:
                results = await _search_feishu(feishu, user, variant)
            except FeishuError:
                break  # 没有用户授权或搜索权限：退回名册的模糊匹配
            for r in results:
                seen.setdefault(r["open_id"], r)
            same = {r["open_id"]: r for r in results if r["name"] in variants or r["name"].lower() == variant.lower()}
            pick = list(same.values()) if same else (results if len(results) == 1 else [])
            if len(pick) == 1:
                await remember(session, [(pick[0]["open_id"], pick[0]["name"], "search")])
                return [{**pick[0], "source": "飞书搜索"}]
        if len(seen) > 1:
            raise Ambiguous(query, list(seen.values())[:6])
        if len(seen) == 1:
            only = next(iter(seen.values()))
            await remember(session, [(only["open_id"], only["name"], "search")])
            return [{**only, "source": "飞书搜索"}]
    # 3. 名册里的模糊匹配
    fuzzy = (await session.execute(
        select(Person).where(or_(*[Person.name.ilike(f"%{v}%") for v in variants]))
        .order_by(Person.updated_at.desc()).limit(limit)
    )).scalars().all()
    return [{"name": p.name, "open_id": p.open_id, "source": "名册"} for p in fuzzy]
