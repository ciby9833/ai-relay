"""路由不能互相遮挡：通配路径写在前面会把后面的固定路径拦下来（批准按钮曾因此一直返回 422）。"""
from types import SimpleNamespace

import httpx

from app import deps
from app.main import app


class NoRows:
    async def get(self, *args, **kwargs):
        return None


async def test_item_routes_reach_their_own_handlers():
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(id="u")
    app.dependency_overrides[deps.get_session] = lambda: NoRows()
    app.dependency_overrides[deps.get_feishu] = lambda: None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as client:
            # 事项不存在时各自的处理函数返回 404；被别的路由拦下会是 422
            response = await client.post("/api/items/1/approval", json={"approve": True})
            assert response.status_code == 404 and response.json()["detail"] == "审批事项不存在"
            for decision in ("done", "dismiss"):
                response = await client.post(f"/api/items/1/{decision}")
                assert response.status_code == 404 and response.json()["detail"] == "事项不存在"
            assert (await client.post("/api/items/1/other")).status_code in (404, 405)
    finally:
        app.dependency_overrides.clear()
