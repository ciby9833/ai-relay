"""记下每一次后台模型调用（判断）：用哪个判断、对象、提示词版本、模型、输入、输出、耗时、出错。

调用处用 `with scope("mail_triage", user_id, f"signal:{id}"):` 包住 complete_structured / complete_text，
模型调用本身（app/proactive/llm.py）在 scope 里时记一条。记录用独立的数据库会话写，失败不影响判断本身。
隐私：记录只属于这个人；管理员只看到汇总数字。保留 RETENTION_DAYS 天。
"""

import hashlib
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.judgements.catalog import JUDGEMENTS, RETENTION_DAYS

logger = logging.getLogger(__name__)
INPUT_LIMIT = 30_000
_scope: ContextVar[dict | None] = ContextVar("relay_judgement_scope", default=None)


@contextmanager
def scope(name: str, user_id: uuid.UUID | None, subject: str | None = None):
    if name not in JUDGEMENTS:
        raise ValueError(f"未登记的判断：{name}")
    token = _scope.set({"name": name, "user_id": user_id, "subject": subject})
    try:
        yield
    finally:
        _scope.reset(token)


def version(system: str) -> str:
    return hashlib.sha256(system.encode()).hexdigest()[:8]


def started() -> float:
    return time.monotonic()


async def save(system: str, prompt: str, model: str, output, error: str | None, since: float) -> None:
    """在 scope 里时记一条；不在 scope 里（测试、一次性脚本）不记。"""
    current = _scope.get()
    if current is None:
        return
    from app.db import SessionLocal
    from app.models import JudgementRun

    try:
        async with SessionLocal() as session:
            session.add(JudgementRun(
                name=current["name"], user_id=current["user_id"], subject=(current["subject"] or "")[:200] or None,
                prompt_version=version(system), model=(model or "")[:100], input=prompt[:INPUT_LIMIT],
                output=output if isinstance(output, dict) else {"text": str(output)[:INPUT_LIMIT]} if output is not None else None,
                error=(error or "")[:500] or None, seconds=round(time.monotonic() - since, 2)))
            await session.commit()
    except Exception:  # noqa: BLE001 - 记录失败不影响判断本身
        logger.warning("记录判断失败 %s", current["name"], exc_info=True)


async def purge() -> int:
    """删掉超过保留期的记录。"""
    from app.db import SessionLocal
    from app.models import JudgementRun

    async with SessionLocal() as session:
        result = await session.execute(delete(JudgementRun).where(
            JudgementRun.created_at < datetime.now(UTC) - timedelta(days=RETENTION_DAYS)))
        await session.commit()
        return result.rowcount or 0


async def judged(name: str, user_id, subject: str | None, call, *args, **kwargs):
    """在一个判断的范围里调用模型（call 是 complete_structured / complete_text），这次调用会被记下。"""
    with scope(name, user_id, subject):
        return await call(*args, **kwargs)
