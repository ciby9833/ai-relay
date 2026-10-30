"""桌面客户端：配对 / 撤销（本人登录后），领活 / 回传（设备令牌）。规则见 app/devices.py。"""

import asyncio
import hashlib
import uuid

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import devices
from app.db import SessionLocal
from app.deps import SessionDep, UserDep
from app.models import Device, GeneratedFile
from app.sources import files

router = APIRouter(tags=["devices"])
WAIT_MAX = 25
READ_TEXT_LIMIT = 60_000


class PairBody(BaseModel):
    name: str = Field(max_length=255)
    platform: str = Field(max_length=32)
    app_version: str | None = Field(default=None, max_length=32)


@router.post("/api/devices")
async def pair(body: PairBody, session: SessionDep, user: UserDep):
    """客户端里登录后配对这台设备。令牌只在这一次返回，客户端存进系统钥匙串。"""
    device, token = await devices.pair(session, user, body.name, body.platform, body.app_version)
    await session.commit()
    return {**devices.describe(device), "token": token}


@router.get("/api/devices")
async def list_devices(session: SessionDep, user: UserDep):
    return [devices.describe(d) for d in await devices.mine(session, user)]


@router.delete("/api/devices/{device_id}")
async def revoke(device_id: uuid.UUID, session: SessionDep, user: UserDep):
    """撤销：这台设备的令牌立刻失效，排队中的步骤不再交给它。"""
    from datetime import UTC, datetime

    device = await session.get(Device, device_id)
    if device is None or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="没有这台设备")
    device.revoked_at = datetime.now(UTC)
    await session.commit()
    return {"ok": True}


# ---------- 设备调用（Authorization: Device <令牌>） ----------

async def _device(session, authorization: str | None) -> Device:
    token = (authorization or "").removeprefix("Device ").strip()
    found = await devices.authenticate(session, token)
    if found is None:
        raise HTTPException(status_code=401, detail="设备未配对或已撤销")
    return found[0]


class FoldersBody(BaseModel):
    folders: list[dict] = Field(default_factory=list, max_length=50)
    app_version: str | None = Field(default=None, max_length=32)


@router.put("/api/device/folders")
async def report_folders(body: FoldersBody, session: SessionDep, authorization: str | None = Header(default=None)):
    """设备上报授权的文件夹（只有名字和读写开关）。"""
    device = await _device(session, authorization)
    device.folders = devices.clean_folders(body.folders)
    if body.app_version:
        device.app_version = body.app_version[:32]
    await session.commit()
    return devices.describe(device)


@router.get("/api/device/jobs")
async def take_jobs(wait: int = 0, authorization: str | None = Header(default=None)):
    """长轮询领活：有活马上返回，没有就最多等 wait 秒。每次来也算一次“在线”。"""
    wait = max(0, min(wait, WAIT_MAX))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    while True:
        async with SessionLocal() as session:  # 每次检查用新的会话，等待期间不占数据库连接
            device = await _device(session, authorization)
            jobs = await devices.claim(session, device)
            if jobs or loop.time() >= deadline:
                return [{"id": str(j.id), "kind": j.kind, "args": j.args} for j in jobs]
        await asyncio.sleep(1)


class ResultBody(BaseModel):
    ok: bool
    data: dict | None = None
    error: str | None = Field(default=None, max_length=1000)


@router.post("/api/device/jobs/{job_id}/result")
async def report_result(job_id: uuid.UUID, body: ResultBody, session: SessionDep, authorization: str | None = Header(default=None)):
    device = await _device(session, authorization)
    try:
        await devices.finish(session, device, job_id, body.data, None if body.ok else (body.error or "执行失败"))
    except devices.DeviceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/api/device/jobs/{job_id}/file")
async def upload_read(job_id: uuid.UUID, request: Request, session: SessionDep, authorization: str | None = Header(default=None),
                      x_relay_modified: str | None = Header(default=None)):
    """读文件：设备把文件原样传上来，这里解析成文字（不保存原文件），记下版本（大小、修改时间、哈希）。"""
    device = await _device(session, authorization)
    try:
        job = await devices.job_for(session, device, job_id)
    except devices.DeviceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job.kind != "read":
        raise HTTPException(status_code=400, detail="这一步不是读文件")
    data = await request.body()
    name = job.args.get("path", "").rsplit("/", 1)[-1] or "file"
    try:
        text = files.to_text(data, name)
        result, error = {"text": text[:READ_TEXT_LIMIT], "truncated": len(text) > READ_TEXT_LIMIT, "filename": name,
                         "size": len(data), "modified": x_relay_modified, "sha256": hashlib.sha256(data).hexdigest()}, None
    except files.FileError as exc:
        result, error = None, str(exc)
    try:
        await devices.finish(session, device, job_id, result, error)
    except devices.DeviceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": error is None}


@router.get("/api/device/jobs/{job_id}/payload")
async def download_payload(job_id: uuid.UUID, session: SessionDep, authorization: str | None = Header(default=None)):
    """存文件：设备来取要写入的内容（Relay 生成的文件，只能是本人的）。"""
    device = await _device(session, authorization)
    try:
        job = await devices.job_for(session, device, job_id)
    except devices.DeviceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job.kind != "write" or job.status != "running":
        raise HTTPException(status_code=400, detail="这一步不是存文件，或已经结束")
    record = await session.get(GeneratedFile, uuid.UUID(job.args["file_id"]))
    if record is None or record.user_id != device.user_id or not record.content:
        raise HTTPException(status_code=404, detail="文件不存在")
    return Response(record.content, media_type="application/octet-stream")
