"""生成文件、存进飞书云空间：按任务做（可能要一阵子），状态记在 GeneratedFile 上。

    排队 → 生成 → 重新打开核对 →（要存云空间的话）上传 → 从云空间下载回来对一遍 → 完成，告诉他

小文件当场做完，对话里直接给结果；内容多的、要上传云空间的交给后台：对话里先说“在做了”，卡片上显示进行到哪一步，
做完（或失败）在飞书里告诉他。worker 每轮会接着做没做完的（进程重启也不丢），失败最多重试 3 次。
"""

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import outputs
from app.db import SessionLocal
from app.feishu.client import FeishuClient, FeishuError
from app.models import GeneratedFile, User

logger = logging.getLogger("relay.filejobs")

INLINE_LIMIT = 20_000  # 工作量超过这个就交给后台
MAX_ATTEMPTS = 3
STALE = timedelta(minutes=10)  # “进行中”超过这么久没动静：当作中断了，重新做
UPLOAD_LIMIT = 20 * 1024 * 1024  # 飞书一次上传的上限


def card(record: GeneratedFile, size: int | None = None) -> dict:
    return {"kind": "file", "file_id": str(record.id), "filename": record.filename, "file_kind": record.kind,
            "size": size or 0, "verified": record.verified or {}, "status": record.status, "stage": record.stage,
            "drive": record.drive, "error": record.error, "sources": (record.spec or {}).get("sources") or []}


async def start(session: AsyncSession, feishu: FeishuClient, user: User, kind: str, filename: str, spec: dict,
                save_to_drive: dict | None = None) -> GeneratedFile:
    """建任务。小的、不用上传的当场做完；其余交给后台（立刻开始，worker 兜底）。"""
    record = GeneratedFile(user_id=user.id, kind=kind, filename=filename, spec=spec, verified={}, status="queued",
                           stage="排队中", save_to_drive=save_to_drive)
    session.add(record)
    await session.flush()
    if save_to_drive is None and outputs.size_of(kind, spec) <= INLINE_LIMIT:
        await _build(record)
        record.status, record.stage = "done", None
        return record
    record.notify = True
    await session.flush()
    kick(record.id, feishu)
    return record


def kick(file_id, feishu: FeishuClient) -> None:
    """马上在后台开始做（不等 worker 的下一轮）。"""
    async def go():
        # 任务记录要等这一轮对话提交后才看得见：先等一会儿再认领，等不到就交给 worker
        for _ in range(30):
            await asyncio.sleep(2)
            try:
                async with SessionLocal() as session:
                    if await process(session, feishu, file_id) is not None:
                        return
            except Exception:  # noqa: BLE001 - 后台任务出错由 worker 重试
                logger.exception("后台生成文件失败 %s", file_id)
                return

    try:
        asyncio.get_running_loop().create_task(go())
    except RuntimeError:
        pass  # 没有事件循环（测试里同步调用）：交给 worker


async def _build(record: GeneratedFile) -> None:
    record.stage = "生成文件"
    data, verified = await asyncio.to_thread(outputs.build, record.kind, record.spec)
    record.content, record.verified = data, verified


async def process(session: AsyncSession, feishu: FeishuClient, file_id) -> GeneratedFile | None:
    """做一个任务（认领后才做，避免两边同时做）。"""
    now = datetime.now(UTC)
    record = (await session.execute(select(GeneratedFile).where(
        GeneratedFile.id == file_id,
        or_(GeneratedFile.status == "queued", (GeneratedFile.status == "running") & (GeneratedFile.updated_at < now - STALE)),
    ).with_for_update(skip_locked=True))).scalars().first()
    if record is None:
        return None
    user = await session.get(User, record.user_id)
    from app import tenancy

    feishu = await tenancy.client_for(session, user, feishu)  # 他自己工作区的飞书；没有飞书就只在 Relay 里告诉他
    record.status, record.attempts, record.updated_at, record.error = "running", record.attempts + 1, now, None
    await session.commit()
    try:
        if record.content is None or not record.verified:
            await _build(record)
            record.updated_at = datetime.now(UTC)
            await session.commit()
        if record.save_to_drive is not None:
            record.stage = "存进飞书云空间"
            await session.commit()
            record.drive = await upload_to_drive(feishu, user, record.content, record.filename, record.save_to_drive.get("folder_token"))
            record.save_to_drive = None
        record.status, record.stage, record.updated_at = "done", None, datetime.now(UTC)
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - 任何一步失败都记下来，交给重试
        logger.exception("生成文件任务失败 %s", record.id)
        await session.rollback()
        await session.refresh(record)
        await session.refresh(user)
        record.error = str(exc)[:500]
        record.status = "failed" if record.attempts >= MAX_ATTEMPTS else "queued"
        record.stage = "失败" if record.status == "failed" else "稍后重试"
        record.updated_at = datetime.now(UTC)
        await session.commit()
    if record.notify and record.status in ("done", "failed"):
        await _tell(session, feishu, user, record)
    return record


async def run_pending(feishu: FeishuClient) -> int:
    """worker 每轮调用：接着做没做完的（包括进程重启前中断的）。"""
    async with SessionLocal() as session:
        ids = list((await session.execute(select(GeneratedFile.id).where(
            or_(GeneratedFile.status == "queued",
                (GeneratedFile.status == "running") & (GeneratedFile.updated_at < datetime.now(UTC) - STALE)),
            GeneratedFile.attempts < MAX_ATTEMPTS,
        ).limit(10))).scalars())
    for file_id in ids:
        async with SessionLocal() as session:
            await process(session, feishu, file_id)
    return len(ids)


async def _tell(session: AsyncSession, feishu: FeishuClient, user: User, record: GeneratedFile) -> None:
    """后台做完了：在飞书里告诉他（成功时把文件发给他，存了云空间就给链接）。"""
    record.notify = False
    await session.commit()
    try:
        if record.status == "failed":
            await feishu.send_text(user.feishu_open_id, f"《{record.filename}》没有做成：{record.error}。可以在 Relay 里让我重试。")
            return
        lines = [f"《{record.filename}》做好了。{'核对通过' if record.verified.get('ok') else '⚠️ 核对不一致'}：{record.verified.get('detail')}"]
        if record.drive:
            check = record.drive.get("verified") or {}
            lines.append(f"已存进你的飞书云空间：{record.drive.get('url')}（{check.get('detail')}）")
        await feishu.send_text(user.feishu_open_id, "\n".join(lines))
        if not record.drive:
            await feishu.send_file(user.feishu_open_id, record.content, record.filename, outputs.FEISHU_FILE_TYPE[record.kind])
    except FeishuError:
        logger.exception("通知文件结果失败 %s", record.id)


async def root_folder(feishu: FeishuClient, user: User) -> str:
    data = await feishu.user_api(user, "GET", "/drive/explorer/v2/root_folder/meta")
    return data["token"]


async def upload_to_drive(feishu: FeishuClient, user: User, data: bytes, filename: str, folder_token: str | None) -> dict:
    """以他本人身份上传到他的云空间（默认“我的空间”根目录），再下载回来比对内容，确认存进去的就是这份。"""
    if len(data) > UPLOAD_LIMIT:
        raise FeishuError("文件超过 20MB，暂不支持存进云空间")
    folder = folder_token or await root_folder(feishu, user)
    uploaded = await feishu.user_api(user, "POST", "/drive/v1/files/upload_all",
                                     data={"file_name": filename, "parent_type": "explorer", "parent_node": folder, "size": str(len(data))},
                                     files={"file": (filename, data)})
    token = uploaded["file_token"]
    metas = (await feishu.user_api(user, "POST", "/drive/v1/metas/batch_query",
                                   json={"request_docs": [{"doc_token": token, "doc_type": "file"}], "with_url": True})).get("metas") or []
    url = (metas[0].get("url") if metas else None) or ""
    back, _ = await feishu.download(f"/drive/v1/files/{token}/download", user=user)
    same = hashlib.sha256(back).hexdigest() == hashlib.sha256(data).hexdigest()
    return {"token": token, "url": url, "folder": folder,
            "verified": {"ok": same, "detail": "从云空间下载回来比对，内容一致" if same else "从云空间下载回来比对，内容不一致"}}
