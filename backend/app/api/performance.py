"""Admin-only, bounded read model for optional monitoring. No arbitrary PromQL proxy."""
import asyncio
import math
import time
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import HTTPException, APIRouter, Response
from sqlalchemy import func, select

from app.api.quality import require_admin
from app.config import get_settings
from app.deps import SessionDep, UserDep
from app.models import Mission, ScheduledTask

router = APIRouter(prefix="/api/admin/performance", tags=["performance"])
Window = Literal["1h", "24h", "7d"]
WINDOWS = {"1h": (3600, 30), "24h": (86400, 300), "7d": (604800, 1800)}
JOBS = ("node", "cadvisor", "api", "worker", "feishu")

# No identity-bearing labels. A down/stale exporter must not appear as live data.
def fresh(job):
    return f'(up{{job="{job}"}} == 1) and (time() - timestamp(up{{job="{job}"}}) < 90)'


HOST = {
    "cpu": '100 * (1 - avg(rate(node_cpu_seconds_total{job="node",mode="idle"}[2m])))',
    "cpu_core": '100 * (1 - avg by(cpu)(rate(node_cpu_seconds_total{job="node",mode="idle"}[2m])))',
    "cores": 'count(node_cpu_seconds_total{job="node",mode="idle"})',
    "iowait": '100 * avg(rate(node_cpu_seconds_total{job="node",mode="iowait"}[2m]))',
    "load": 'node_load1{job="node"}',
    "memory": '100 * (1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"})',
    "memory_total": 'node_memory_MemTotal_bytes{job="node"}',
    "memory_available": 'node_memory_MemAvailable_bytes{job="node"}',
    "swap_used": 'node_memory_SwapTotal_bytes{job="node"} - node_memory_SwapFree_bytes{job="node"}',
    "swap_total": 'node_memory_SwapTotal_bytes{job="node"}',
    "disk_total": 'node_filesystem_size_bytes{job="node",fstype!~"tmpfs|overlay|squashfs|nsfs",device!~"/dev/loop.*"} > 0',
    "disk_free": 'node_filesystem_avail_bytes{job="node",fstype!~"tmpfs|overlay|squashfs|nsfs",device!~"/dev/loop.*"}',
    "disk_read": 'rate(node_disk_read_bytes_total{job="node",device!~"loop.*|ram.*"}[2m])',
    "disk_write": 'rate(node_disk_written_bytes_total{job="node",device!~"loop.*|ram.*"}[2m])',
    "disk_latency": '(rate(node_disk_read_time_seconds_total{job="node",device!~"loop.*|ram.*"}[2m]) + rate(node_disk_write_time_seconds_total{job="node",device!~"loop.*|ram.*"}[2m])) / (rate(node_disk_reads_completed_total{job="node",device!~"loop.*|ram.*"}[2m]) + rate(node_disk_writes_completed_total{job="node",device!~"loop.*|ram.*"}[2m]))',
    "node_collectors": 'node_scrape_collector_success{job="node",collector=~"cpu|meminfo|filesystem|diskstats|loadavg|vmstat|time"}',
    "oom": 'increase(node_vmstat_oom_kill{job="node"}[1h])',
    "host_sample": 'timestamp(node_time_seconds{job="node"})',
}
# Do not turn a filesystem stat/permission failure into a full disk (0 available).
for key in ("disk_total", "disk_free"):
    HOST[key] = f'({HOST[key]}) and on(job,instance,device,mountpoint) (node_filesystem_device_error{{job="node"}} == 0)'

CONTAINER_FRESH = '(time() - container_last_seen{job="cadvisor"} < 90)'
CONTAINERS = {
    "network_rx": f'sum(rate(container_network_receive_bytes_total{{job="cadvisor",service=~"api|worker|feishu|db|web",interface!="lo"}}[2m]) and on(job,instance,id) {CONTAINER_FRESH})',
    "network_tx": f'sum(rate(container_network_transmit_bytes_total{{job="cadvisor",service=~"api|worker|feishu|db|web",interface!="lo"}}[2m]) and on(job,instance,id) {CONTAINER_FRESH})',
    # CPU expressed as cores, not an ambiguous 0–100% for multi-core containers.
    "service_cpu": f'sum by(service)(rate(container_cpu_usage_seconds_total{{job="cadvisor",service!=""}}[2m]) and on(job,instance,id) {CONTAINER_FRESH})',
    "service_memory": f'sum by(service)(container_memory_working_set_bytes{{job="cadvisor",service!=""}} and on(job,instance,id) {CONTAINER_FRESH})',
    "service_seen": 'max by(service)(container_last_seen{job="cadvisor",service!=""})',
}
APP = {
    "inflight": 'sum by(kind)(relay_inflight and on(job,instance) ((up == 1) and (time() - timestamp(up) < 90)) and on(job,instance) (time() - relay_heartbeat_timestamp_seconds < 45))',
    "heartbeat_age": 'time() - relay_heartbeat_timestamp_seconds',
    "worker_cycle_age": 'time() - (relay_worker_cycle_timestamp_seconds{job="worker"} > 0)',
    "turn_p95": 'histogram_quantile(0.95, sum by(le)(rate(relay_work_seconds_bucket{kind="turn"}[5m])))',
    "tool_p95": 'histogram_quantile(0.95, sum by(le)(rate(relay_work_seconds_bucket{kind="tool"}[5m])))',
    "llm_p95": 'histogram_quantile(0.95, sum by(le,provider)(rate(relay_llm_seconds_bucket[5m])))',
    "llm_first": 'histogram_quantile(0.95, sum by(le,provider)(rate(relay_llm_first_text_seconds_bucket[5m])))',
    "llm_calls": 'sum by(provider,outcome)(increase(relay_llm_seconds_count[1h]))',
    "tokens": 'sum by(provider,direction)(increase(relay_llm_tokens_total[1h]))',
    "targets": 'up',
    "target_age": 'time() - timestamp(up)',
}
COLLECTORS = {
    "cpu": ("cpu", "cpu_core", "cores", "iowait"), "meminfo": ("memory", "memory_total", "memory_available", "swap_used", "swap_total"),
    "filesystem": ("disk_total", "disk_free"), "diskstats": ("disk_read", "disk_write", "disk_latency"),
    "loadavg": ("load",), "vmstat": ("oom",), "time": ("host_sample",),
}
for collector, keys in COLLECTORS.items():
    for key in keys:
        HOST[key] = f'({HOST[key]}) and on() (node_scrape_collector_success{{job="node",collector="{collector}"}} == 1)'

QUERIES = {**{key: f'({value}) and on() ({fresh("node")})' for key, value in HOST.items()},
           **{key: f'({value}) and on() ({fresh("cadvisor")})' for key, value in CONTAINERS.items()}, **APP}
HISTORY = ("cpu", "memory", "disk_free", "disk_read", "disk_write", "network_rx", "network_tx", "inflight", "llm_p95")


def expression(keys):
    return " or ".join(f'label_replace(({QUERIES[key]}), "metric", "{key}", "", "")' for key in keys)


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def decode(payload):
    if payload.get("status") != "success" or not isinstance(payload.get("data", {}).get("result"), list):
        raise ValueError("Invalid monitoring response")
    result = {}
    for row in payload["data"]["result"]:
        labels = row.get("metric", {})
        key = labels.get("metric")
        if key not in QUERIES:
            continue
        points = row.get("values", [row["value"]] if "value" in row else [])
        result.setdefault(key, []).append({
            "labels": {k: v for k, v in labels.items() if k in ("cpu", "mountpoint", "device", "service", "provider", "outcome", "direction", "kind", "job", "collector")},
            "points": [[float(t), finite(v)] for t, v in points],
        })
    return result


async def read_prometheus(window):
    seconds, step = WINDOWS[window]
    now = time.time()
    async with httpx.AsyncClient(base_url=get_settings().prometheus_url.rstrip("/"), timeout=5, trust_env=False) as client:
        async def query(path, params):
            response = await client.get(path, params={**params, "timeout": "4s"})
            response.raise_for_status()
            return decode(response.json())
        rows = await asyncio.gather(
            query("/api/v1/query", {"query": expression(QUERIES), "time": now}),
            query("/api/v1/query_range", {"query": expression(HISTORY), "start": now - seconds, "end": now, "step": step}),
            return_exceptions=True,
        )
    current, history = rows
    failed = [name for name, row in zip(("current", "history"), rows) if isinstance(row, Exception)]
    return {"current": {} if "current" in failed else current, "history": {} if "history" in failed else history,
            "errors": failed, "step": step, "start": now - seconds, "end": now}


async def queue_snapshot(session):
    """Count timer-ready records only. Never poll external event sources to render this page."""
    now = datetime.now(UTC)
    result = {}
    for key, model, condition in (
        ("scheduled", ScheduledTask, ScheduledTask.enabled.is_(True)),
        ("missions", Mission, Mission.status.in_(("active", "waiting"))),
    ):
        count, oldest = (await session.execute(select(func.count(), func.min(model.next_run_at)).where(
            condition, model.next_run_at <= now,
        ))).one()
        result[key] = {"due": count, "oldest_seconds": max(0, (now - oldest).total_seconds()) if oldest else 0}
    return result


_cache = {}
_lock = asyncio.Lock()


@router.get("")
async def performance(session: SessionDep, user: UserDep, response: Response, window: Window = "1h"):
    require_admin(user)
    from app.models import DEFAULT_TENANT_ID

    if user.tenant_id != DEFAULT_TENANT_ID:
        # 服务器和容器的运行状况是整个平台的，不属于任何一家客户：只给平台方（默认工作区）的管理员看
        raise HTTPException(status_code=403, detail="只有平台管理员可以查看")
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    if not settings.monitoring_enabled:
        return {"status": "disabled", "gpu": "not_configured", "current": {}, "history": {}, "queue": None,
                "targets": {}, "errors": [], "window": window, "collected_at": None}
    # Authentication opened a transaction. Release its connection before waiting
    # on Prometheus or the single-flight lock, so slow monitoring cannot pin the
    # business connection pool. The same session can reopen for the short read below.
    await session.close()
    # A bounded cache and single-flight prevent multiple admin tabs multiplying query load.
    async with _lock:
        key = (settings.prometheus_url, window)
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 15:
            return cached[1]
        try:
            data = await read_prometheus(window)
        except Exception:
            now = time.time()
            seconds, step = WINDOWS[window]
            data = {"current": {}, "history": {}, "errors": ["current", "history"],
                    "start": now - seconds, "end": now, "step": step}
        try:
            async with asyncio.timeout(2):
                queue = await queue_snapshot(session)
        except Exception:
            queue = None
            data["errors"].append("queue")
        target_values = {r["labels"].get("job"): r["points"][-1][1] for r in data["current"].get("targets", []) if r["points"]}
        target_ages = {r["labels"].get("job"): r["points"][-1][1] for r in data["current"].get("target_age", []) if r["points"]}
        targets = {job: ("unknown" if job not in target_values else "up" if target_values[job] == 1 and target_ages.get(job) is not None and target_ages[job] < 90 else "down") for job in JOBS}
        for row in data["current"].get("node_collectors", []):
            if not row["points"] or row["points"][-1][1] != 1:
                data["errors"].append("collector." + row["labels"].get("collector", "unknown"))
        status = "unavailable" if "current" in data["errors"] else "partial" if data["errors"] or any(v != "up" for v in targets.values()) else "ok"
        result = {**data, "queue": queue, "status": status, "targets": targets,
                  "gpu": "not_configured", "window": window, "collected_at": time.time()}
        if len(_cache) >= 3:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), result)
        return result
