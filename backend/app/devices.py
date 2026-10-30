"""桌面客户端（第一版：Mac）：配对、领取要在本机做的一步、回传结果。

设计（见 docs/DESKTOP_APP_EVALUATION.md 5.4）：
- 设备是一种执行者，不是另一个助理：任务状态只在云端，设备只回传执行结果和证据。
- 三层授权同时满足才执行：用户交代了（助理调用工具）、目录授权（设备上报的文件夹，读写分开）、设备仍有效（没撤销）。
  目录的最终检查在设备上做（路径、软链接都不能越出授权目录）；云端这里先挡一次。
- 云端只知道文件夹的名字和相对路径，不知道完整路径。
- 同一步只执行一次：设备领取时标记 running；超时没回来的写入算“结果未知”，不重做，让他去看一眼。
"""

import asyncio
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device, DeviceJob, User

ONLINE = timedelta(seconds=75)  # 客户端每 25 秒左右来领一次活；超过这个时间没来算离线
QUEUE_TTL = timedelta(minutes=2)  # 没被领走的步骤过期，不在设备上线后补做（那时他可能已经不需要了）
KINDS = ("list", "read", "write")


class DeviceError(Exception):
    """给用户（和助理）看的话。"""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def pair(session: AsyncSession, user: User, name: str, platform: str, app_version: str | None) -> tuple[Device, str]:
    token = secrets.token_urlsafe(32)
    device = Device(user_id=user.id, name=(name or "Mac")[:255], platform=(platform or "darwin")[:32],
                    app_version=(app_version or "")[:32] or None, token_hash=token_hash(token), last_seen_at=datetime.now(UTC))
    session.add(device)
    await session.flush()
    return device, token


async def authenticate(session: AsyncSession, token: str | None) -> tuple[Device, User] | None:
    if not token:
        return None
    device = (await session.execute(select(Device).where(Device.token_hash == token_hash(token)))).scalars().first()
    if device is None or device.revoked_at is not None:
        return None
    user = await session.get(User, device.user_id)
    if user is None or user.status != "active":
        return None
    return device, user


def online(device: Device) -> bool:
    return device.revoked_at is None and device.last_seen_at is not None and device.last_seen_at > datetime.now(UTC) - ONLINE


async def mine(session: AsyncSession, user: User) -> list[Device]:
    return list((await session.execute(select(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None))
                                       .order_by(Device.last_seen_at.desc().nulls_last()))).scalars())


async def current(session: AsyncSession, user: User) -> Device:
    """替他在本机做事用哪台：最近在线的那台。没有配对或不在线时说清楚。"""
    devices = await mine(session, user)
    if not devices:
        raise DeviceError("你还没有安装或登录 Relay 的 Mac 客户端，本机文件只能在客户端里授权后使用")
    live = [d for d in devices if online(d)]
    if not live:
        raise DeviceError(f"你的 Mac（{devices[0].name}）现在不在线：打开 Relay 客户端后再试")
    return live[0]


def folder(device: Device, name: str, need: str) -> dict:
    """按名字找授权文件夹，并检查读 / 写权限（设备上还会再检查一次）。"""
    for entry in device.folders or []:
        if entry.get("label") == name or entry.get("id") == name:
            if not entry.get(need):
                raise DeviceError(f"文件夹「{entry.get('label')}」没有授权{'写入' if need == 'write' else '读取'}，可以在客户端的设置里打开")
            return entry
    names = "、".join(f.get("label", "") for f in device.folders or []) or "还没有"
    raise DeviceError(f"没有授权名为「{name}」的文件夹（已授权：{names}）。请在 Relay 客户端的设置里添加")


def _safe_path(path: str | None) -> str:
    """相对路径：不能是绝对路径，不能有 ..（设备上按真实路径再检查一次，软链接也挡）。"""
    path = (path or "").replace("\\", "/").strip()
    if path.startswith("/") or path.startswith("~") or (len(path) > 1 and path[1] == ":") or any(part == ".." for part in path.split("/")):
        raise DeviceError("路径只能是授权文件夹里的相对路径")
    return "/".join(part for part in path.split("/") if part not in ("", "."))


async def request(session: AsyncSession, user: User, kind: str, args: dict, timeout: float = 30) -> dict:
    """交给他的 Mac 做一步，等结果。"""
    if kind not in KINDS:
        raise DeviceError("不支持的操作")
    device = await current(session, user)
    need = "write" if kind == "write" else "read"
    entry = folder(device, args.get("folder") or "", need)
    from app.db import SessionLocal

    # 用单独的数据库会话排队和等待：不提交调用方（对话这一轮）手上还没提交的改动
    async with SessionLocal() as own:
        job = DeviceJob(device_id=device.id, user_id=user.id, kind=kind,
                        args={**args, "folder": entry["id"], "path": _safe_path(args.get("path"))})
        own.add(job)
        await own.commit()
        job_id = job.id
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)
            own.expire_all()
            job = await own.get(DeviceJob, job_id)
            if job.status in ("done", "failed"):
                break
        return await _outcome(own, job)


async def _outcome(session: AsyncSession, job: DeviceJob) -> dict:
    if job.status == "done":
        return job.result or {}
    if job.status == "failed":
        raise DeviceError((job.result or {}).get("error") or "Mac 上执行失败")
    if job.status == "queued":
        # 只在仍然没被领走时才作废（和设备领取同时发生时，以领取为准）
        expired = await session.execute(update(DeviceJob).where(DeviceJob.id == job.id, DeviceJob.status == "queued")
                                        .values(status="expired", finished_at=datetime.now(UTC)))
        await session.commit()
        if expired.rowcount:
            raise DeviceError("你的 Mac 没有及时响应（可能刚休眠或断网），这一步没有执行")
    # 已经领走但没回来：结果未知，不重做（写入可能已经发生）
    raise DeviceError("Mac 上这一步还没回报结果，结果未知：如果是保存文件，请先到文件夹里看一下，不要重复保存")


async def claim(session: AsyncSession, device: Device) -> list[DeviceJob]:
    """设备来领活：把排队中的步骤标成执行中（同一步只给一次）。过期的不给。"""
    now = datetime.now(UTC)
    await session.execute(update(DeviceJob).where(DeviceJob.device_id == device.id, DeviceJob.status == "queued",
                                                  DeviceJob.created_at < now - QUEUE_TTL).values(status="expired", finished_at=now))
    jobs = list((await session.execute(select(DeviceJob).where(DeviceJob.device_id == device.id, DeviceJob.status == "queued")
                                       .order_by(DeviceJob.created_at).limit(5).with_for_update(skip_locked=True))).scalars())
    for job in jobs:
        job.status, job.claimed_at = "running", now
    device.last_seen_at = now
    await session.commit()
    return jobs


async def job_for(session: AsyncSession, device: Device, job_id: uuid.UUID) -> DeviceJob:
    job = await session.get(DeviceJob, job_id)
    if job is None or job.device_id != device.id:
        raise DeviceError("没有这一步")
    return job


async def finish(session: AsyncSession, device: Device, job_id: uuid.UUID, result: dict | None, error: str | None) -> DeviceJob:
    """回传结果。重复回传同一步不覆盖第一次的结果。"""
    job = await job_for(session, device, job_id)
    if job.status in ("done", "failed"):
        return job
    if job.status != "running":
        raise DeviceError("这一步已经过期")
    job.status = "failed" if error else "done"
    job.result = {"error": error[:1000]} if error else (result or {})
    job.finished_at = datetime.now(UTC)
    device.last_seen_at = job.finished_at
    await session.commit()
    return job


def clean_folders(raw: list) -> list[dict]:
    """设备上报的授权文件夹：只收 id、名字、读写开关（不收完整路径）。"""
    out, seen = [], set()
    for entry in raw or []:
        if not isinstance(entry, dict) or not entry.get("id") or entry["id"] in seen:
            continue
        seen.add(entry["id"])
        out.append({"id": str(entry["id"])[:64], "label": str(entry.get("label") or "文件夹")[:120],
                    "read": bool(entry.get("read", True)), "write": bool(entry.get("write", False))})
    return out[:50]


def describe(device: Device) -> dict:
    return {"id": str(device.id), "name": device.name, "platform": device.platform, "app_version": device.app_version,
            "online": online(device), "folders": device.folders or [],
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "created_at": device.created_at.isoformat() if device.created_at else None}
