"""Mac 客户端：配对、授权文件夹、领活、读文件、存文件、撤销、离线。设备用一个假的客户端模拟（虚构数据）。"""
import asyncio
import hashlib
import io
import os
import uuid

import httpx
import pytest

from app import devices

pytestmark = pytest.mark.skipif(not os.getenv("RUN_DB_TESTS"), reason="需要 RUN_DB_TESTS=1 和数据库")


def test_paths_must_stay_inside_the_authorised_folder():
    assert devices._safe_path("./报价/9月.xlsx") == "报价/9月.xlsx"
    for bad in ("/etc/passwd", "../secret", "a/../../b", "~/x", "C:/Windows"):
        with pytest.raises(devices.DeviceError):
            devices._safe_path(bad)


async def test_mac_reads_and_saves_files_only_in_authorised_folders():
    from openpyxl import Workbook
    from sqlalchemy import delete, select

    from app import tenancy
    from app.agent.tools import local
    from app.agent.tools.base import ToolContext, ToolError
    from app.db import SessionLocal, engine
    from app.main import app
    from app.models import Account, Device, DeviceJob, GeneratedFile, Tenant, User

    tag = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        account = Account(email=f"mac-{tag}@co.test", name="Mac User", password_hash=tenancy.hash_password("mac-pass-123"))
        session.add(account)
        await session.flush()
        user = await tenancy.create_workspace(session, account, f"Mac {tag}")
        book = Workbook()
        book.active.append(["单号", "重量"])
        book.active.append(["JT001", 12])
        buffer = io.BytesIO()
        book.save(buffer)
        report = GeneratedFile(user_id=user.id, kind="xlsx", filename="周报.xlsx", content=b"PK-fake-report", spec={}, status="done")
        session.add(report)
        await session.commit()
        user_id, tenant_id, report_id, sheet = user.id, user.tenant_id, report.id, buffer.getvalue()

    web = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay")
    await web.post("/api/auth/login", json={"email": f"mac-{tag}@co.test", "password": "mac-pass-123"})
    try:
        async with SessionLocal() as session:
            ctx = ToolContext(session=session, user=await session.get(User, user_id), conversation=None, feishu=None)
            # 还没装客户端：明确说，不假装做了
            with pytest.raises(ToolError, match="还没有安装"):
                await local.read_local_file(ctx, {"folder": "报价", "path": "a.xlsx"})

        paired = (await web.post("/api/devices", json={"name": "Ellis 的 MacBook", "platform": "darwin", "app_version": "0.1.0"})).json()
        token = paired["token"]
        mac = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay", headers={"Authorization": f"Device {token}"})
        await mac.put("/api/device/folders", json={"folders": [
            {"id": "f1", "label": "报价", "read": True, "write": False, "path": "/Users/ellis/报价"},
            {"id": "f2", "label": "成果", "read": True, "write": True}]})
        listed = (await web.get("/api/devices")).json()
        assert listed[0]["online"] and listed[0]["folders"][0] == {"id": "f1", "label": "报价", "read": True, "write": False}  # 不收完整路径

        written: dict = {}

        async def fake_mac(rounds: int):
            """模拟客户端：领活 → 执行 → 回传。"""
            for _ in range(rounds):
                for job in (await mac.get("/api/device/jobs", params={"wait": 2})).json():
                    if job["kind"] == "list":
                        await mac.post(f"/api/device/jobs/{job['id']}/result", json={"ok": True, "data": {"entries": [
                            {"path": "9月报价.xlsx", "size": 4096, "modified": "2026-10-29T10:00:00Z"}, {"path": "旧", "dir": True}]}})
                    elif job["kind"] == "read":
                        assert job["args"] == {"folder": "f1", "path": "9月报价.xlsx"}
                        await mac.post(f"/api/device/jobs/{job['id']}/file", content=sheet, headers={"X-Relay-Modified": "2026-10-29T10:00:00Z"})
                    elif job["kind"] == "write":
                        content = (await mac.get(f"/api/device/jobs/{job['id']}/payload")).content
                        assert hashlib.sha256(content).hexdigest() == job["args"]["sha256"]
                        written[job["args"]["path"]] = content
                        await mac.post(f"/api/device/jobs/{job['id']}/result", json={"ok": True, "data": {
                            "path": "周报 (1).xlsx", "verified": True}})  # 同名已存在：换名，不覆盖

        async with SessionLocal() as session:
            ctx = ToolContext(session=session, user=await session.get(User, user_id), conversation=None, feishu=None)
            def call(handler, args):
                return handler(ctx, args)

            listing, _ = await asyncio.gather(call(local.list_local_files, {"folder": "报价"}), fake_mac(2))
            assert "9月报价.xlsx" in listing and "📁 旧" in listing
            content, _ = await asyncio.gather(call(local.read_local_file, {"folder": "报价", "path": "9月报价.xlsx"}), fake_mac(2))
            assert "JT001" in content and "sha256" in content
            # 只读的文件夹不能写；路径不能越出授权文件夹
            with pytest.raises(ToolError, match="没有授权写入"):
                await call(local.save_file_to_mac, {"file_id": str(report_id), "folder": "报价"})
            with pytest.raises(ToolError, match="相对路径"):
                await call(local.read_local_file, {"folder": "报价", "path": "../../.ssh/id_rsa"})
            saved, _ = await asyncio.gather(call(local.save_file_to_mac, {"file_id": str(report_id), "folder": "成果"}), fake_mac(2))
            assert "周报 (1).xlsx" in saved and "没有覆盖" in saved and written == {"周报.xlsx": b"PK-fake-report"}

            # 同一步只执行一次：重复回传不覆盖
            job = (await session.execute(select(DeviceJob).where(DeviceJob.user_id == user_id, DeviceJob.kind == "write"))).scalars().first()
            await mac.post(f"/api/device/jobs/{job.id}/result", json={"ok": False, "error": "again"})
            assert await session.scalar(select(DeviceJob.status).where(DeviceJob.id == job.id).execution_options(populate_existing=True)) == "done"

        # 撤销后令牌立刻失效
        assert (await web.delete(f"/api/devices/{paired['id']}")).status_code == 200
        assert (await mac.get("/api/device/jobs")).status_code == 401
        await mac.aclose()
    finally:
        await web.aclose()
        async with SessionLocal() as session:
            await session.execute(delete(Device).where(Device.user_id == user_id))
            await session.execute(delete(GeneratedFile).where(GeneratedFile.user_id == user_id))
            await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.execute(delete(Account).where(Account.email.like(f"%{tag}%")))
            await session.commit()
        await engine.dispose()
