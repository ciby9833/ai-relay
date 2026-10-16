"""组织架构：部门、部门负责人、成员、个人资料（职位、部门、直属上级）。

以用户本人的身份查询，看到的范围和他在飞书通讯录里能看到的一致（不受应用通讯录权限范围限制）。
"""

from app.feishu.client import FeishuClient, FeishuError
from app.models import User

DEPT = {"department_id_type": "open_department_id", "user_id_type": "open_id"}


class Org:
    """一次对话里的组织架构查询（带缓存，避免反复查同一个人/部门）。"""

    def __init__(self, feishu: FeishuClient, user: User):
        self.feishu, self.user = feishu, user
        self._users: dict[str, dict] = {}
        self._depts: dict[str, dict] = {}

    async def _get(self, path: str, **params) -> dict:
        return await self.feishu.user_api(self.user, "GET", path, params={**DEPT, **params})

    async def person(self, open_id: str) -> dict:
        if open_id not in self._users:
            try:
                self._users[open_id] = (await self._get(f"/contact/v3/users/{open_id}")).get("user") or {}
            except FeishuError:
                self._users[open_id] = {}
        return self._users[open_id]

    async def name(self, open_id: str | None) -> str | None:
        if not open_id:
            return None
        person = await self.person(open_id)
        name, en = person.get("name"), person.get("en_name")
        if name and en and en.lower() not in name.lower():
            return f"{name}（{en}）"
        return name or en

    async def department(self, dept_id: str) -> dict:
        if dept_id not in self._depts:
            try:
                self._depts[dept_id] = (await self._get(f"/contact/v3/departments/{dept_id}")).get("department") or {}
            except FeishuError:
                self._depts[dept_id] = {}
        return self._depts[dept_id]

    async def path(self, dept_id: str, depth: int = 6) -> list[str]:
        """从上到下的部门路径，例如 总部 / IT 中心 / 网络组。"""
        names = []
        current = dept_id
        for _ in range(depth):
            if not current or current == "0":
                break
            dept = await self.department(current)
            if not dept:
                break
            names.append(dept.get("name") or "?")
            current = dept.get("parent_department_id")
        return names[::-1]

    async def search_departments(self, query: str, limit: int = 8) -> list[dict]:
        data = await self.feishu.user_api(
            self.user, "POST", "/contact/v3/departments/search", params={**DEPT, "page_size": limit}, json={"query": query}
        )
        results = []
        for dept in (data.get("items") or [])[:limit]:
            dept_id = dept.get("open_department_id")
            leader_ids = [dept.get("leader_user_id")] + [l.get("leaderID") for l in dept.get("leaders") or []]
            leaders = [n for n in [await self.name(i) for i in dict.fromkeys(i for i in leader_ids if i)] if n]
            results.append({
                "id": dept_id, "name": dept.get("name"), "leaders": leaders,
                "members": dept.get("member_count"), "path": " / ".join(await self.path(dept.get("parent_department_id") or "0")),
            })
        return results

    async def members(self, dept_id: str, limit: int = 50) -> list[dict]:
        data = await self._get("/contact/v3/users/find_by_department", department_id=dept_id, page_size=limit)
        return [
            {"name": await self.name(u.get("open_id")) or u.get("name"), "open_id": u.get("open_id"),
             "title": u.get("job_title")}
            for u in data.get("items") or []
        ]

    async def profile(self, open_id: str) -> dict:
        person = await self.person(open_id)
        departments = [" / ".join(await self.path(d)) for d in (person.get("department_ids") or [])[:3]]
        return {
            "name": await self.name(open_id), "title": person.get("job_title"),
            "departments": [d for d in departments if d], "manager": await self.name(person.get("leader_user_id")),
            "email": person.get("enterprise_email") or person.get("email"), "city": person.get("city"),
        }
