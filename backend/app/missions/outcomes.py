"""Immutable acceptance contracts; observations come from connectors, never model-supplied values."""
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SheetRule(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    spreadsheet_token: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    sheet_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    cell: str = Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")
    scope: str = Field(min_length=1, max_length=300, description="业务对象、指标和统计口径，例如 A 网点当前异常件数")
    operator: Literal["decrease", "lt", "lte", "eq", "gte", "gt"]
    target: float | None = None


class CriterionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=300)
    requirement: Literal["execution", "reply", "business"] = "reply"
    rule: SheetRule | None = None


def number(raw) -> Decimal:
    if isinstance(raw, bool) or raw is None:
        raise ValueError("指标不是有效数值")
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise ValueError("指标不是有效数值") from exc
    if not value.is_finite():
        raise ValueError("指标不是有限数值")
    return value


async def observe(feishu, user, rule: dict) -> dict:
    from app.sources.sheets import read_cells

    checked = SheetRule.model_validate(rule)
    values = await read_cells(feishu, user, checked.spreadsheet_token, checked.sheet_id, [checked.cell])
    value = number(values.get(checked.cell))
    return {"value": str(value), "at": datetime.now(UTC).isoformat(), "source": checked.model_dump()}


async def capture_baselines(feishu, user, items: list[dict]) -> None:
    for item in items:
        rule = item.get("rule")
        if rule and rule["operator"] == "decrease" and not item.get("baseline"):
            try:
                item["baseline"] = await observe(feishu, user, rule)
            except Exception:
                # Missing baseline must not silently become a model-provided number.
                item["baseline"] = None


async def evaluate(feishu, user, item: dict) -> dict:
    rule = item.get("rule")
    if not rule:
        return {"ok": None, "detail": "尚未绑定业务系统指标，不能用催办或对方声称已处理代替业务结果"}
    try:
        observation = await observe(feishu, user, rule)
        current = number(observation["value"])
        if rule["operator"] == "decrease":
            baseline = item.get("baseline")
            if not baseline or baseline.get("source") != rule:
                return {"ok": None, "detail": "缺少接任务时的同口径基线，请用户重新设置核验来源"}
            target = number(baseline["value"])
            ok = current < target
        else:
            target = number(rule.get("target"))
            ok = {"lt": current < target, "lte": current <= target, "eq": current == target,
                  "gte": current >= target, "gt": current > target}[rule["operator"]]
        return {"ok": ok, "detail": f"{rule['scope']}：回读 {current}；{rule['operator']} {target}",
                "observation": observation, "target": str(target)}
    except Exception:
        return {"ok": None, "detail": "业务指标回读失败或值无效，尚不能确认目标达成"}
