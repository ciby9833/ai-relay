"""Optional, process-local measurements. No network calls on business execution paths.

Each existing process exposes its own internal scrape endpoint. Prometheus aggregates
them; do not run multiple API workers on the same port without changing this setup.
No user IDs, prompts, URLs or exception text are exported as labels.
"""
import asyncio
import logging
import math
import time
from contextlib import contextmanager

from app.config import get_settings
from app.llm.base import Completion, TextDelta

logger = logging.getLogger(__name__)
# Development bind mounts may load new code into an older image. Metrics must
# never become a mandatory import-time dependency for the business service.
try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

    REGISTRY = CollectorRegistry()
    BUCKETS = (.1, .5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800, 3600)
    INFLIGHT = Gauge("relay_inflight", "Currently executing work", ["kind"], registry=REGISTRY)
    DURATION = Histogram("relay_work_seconds", "Work duration", ["kind", "outcome"], buckets=BUCKETS, registry=REGISTRY)
    LLM_DURATION = Histogram("relay_llm_seconds", "Model request duration including tool arguments", ["provider", "outcome"], buckets=BUCKETS, registry=REGISTRY)
    LLM_FIRST = Histogram("relay_llm_first_text_seconds", "Time to first nonempty text delta; tool-only responses excluded", ["provider"], buckets=BUCKETS, registry=REGISTRY)
    TOKENS = Counter("relay_llm_tokens", "Provider-reported tokens, not billing estimates", ["provider", "direction"], registry=REGISTRY)
    HEARTBEAT = Gauge("relay_heartbeat_timestamp_seconds", "Last event-loop heartbeat", registry=REGISTRY)
    PROGRESS = Gauge("relay_worker_cycle_timestamp_seconds", "Last completed scheduler cycle (not a success verdict)", registry=REGISTRY)
except Exception:
    REGISTRY = None
    logger.warning("Monitoring library unavailable; business service continues. Rebuild the image to enable metrics.")


def enabled():
    return REGISTRY is not None and get_settings().monitoring_enabled


def _safe(operation):
    # A monitoring failure must not replace a business result or exception.
    try:
        operation()
    except Exception:
        logger.warning("Could not record telemetry", exc_info=True)


@contextmanager
def work(kind):
    if not enabled():
        yield
        return
    started, outcome = time.monotonic(), "success"
    _safe(lambda: INFLIGHT.labels(kind).inc())
    try:
        yield
    except BaseException as exc:
        outcome = "cancelled" if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) else "error"
        raise
    finally:
        _safe(lambda: INFLIGHT.labels(kind).dec())
        _safe(lambda: DURATION.labels(kind, outcome).observe(time.monotonic() - started))


def _outcome(exc):
    # Adapters retain the original SDK exception as __cause__.
    for _ in range(5):
        if exc is None:
            break
        if getattr(exc, "status_code", None) == 429 or getattr(exc, "code", None) == 429:
            return "limited"
        if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
            return "timeout"
        exc = exc.__cause__
    return "error"


class ObservedProvider:
    def __init__(self, provider):
        self.provider, self.name = provider, provider.name

    async def stream(self, **kwargs):
        if not enabled():
            async for event in self.provider.stream(**kwargs):
                yield event
            return
        started, first, outcome = time.monotonic(), False, "error"
        _safe(lambda: INFLIGHT.labels("llm").inc())
        stream = None
        try:
            stream = self.provider.stream(**kwargs)
            async for event in stream:
                if isinstance(event, TextDelta) and event.text and not first:
                    first = True
                    _safe(lambda: LLM_FIRST.labels(self.name).observe(time.monotonic() - started))
                if isinstance(event, Completion):
                    outcome = "success"
                    _safe(lambda: _record_usage(self.name, event.usage))
                yield event
        except (asyncio.CancelledError, GeneratorExit):
            outcome = "cancelled"
            raise
        except Exception as exc:
            outcome = _outcome(exc)
            raise
        finally:
            _safe(lambda: INFLIGHT.labels("llm").dec())
            _safe(lambda: LLM_DURATION.labels(self.name, outcome).observe(time.monotonic() - started))
            if stream is not None:
                try:
                    await stream.aclose()
                except Exception:
                    logger.warning("Could not close observed stream", exc_info=True)


def _record_usage(provider, usage):
    if not isinstance(usage, dict):
        return
    for direction in ("input", "output"):
        count = usage.get(f"{direction}_tokens")
        if isinstance(count, (int, float)) and not isinstance(count, bool) and math.isfinite(count) and count >= 0:
            TOKENS.labels(provider, direction).inc(count)


def _initialize():
    # Establish zero baselines for errors too, so the first 429/timeout is not
    # silently lost merely because that labelled counter did not exist before.
    settings = get_settings()
    providers = [name for name in ("anthropic", "openai", "gemini") if getattr(settings, f"{name}_api_key", "")]
    if getattr(settings, "google_application_credentials", "") or getattr(settings, "google_cloud_project", ""):
        providers.append("gemini")
    for provider in set(providers):
        for outcome in ("success", "error", "limited", "timeout", "cancelled"):
            LLM_DURATION.labels(provider, outcome)
        LLM_FIRST.labels(provider)
        for direction in ("input", "output"):
            TOKENS.labels(provider, direction)
    for kind in ("turn", "tool", "llm", "scheduled", "mission"):
        INFLIGHT.labels(kind)
        for outcome in ("success", "error", "cancelled"):
            DURATION.labels(kind, outcome)


async def _heartbeat():
    while True:
        _safe(lambda: HEARTBEAT.set(time.time()))
        await asyncio.sleep(10)


def start():
    """Call on the process's business event loop. Bind errors are nonfatal."""
    if not enabled():
        return None
    try:
        _initialize()
        server, thread = start_http_server(get_settings().monitoring_port, registry=REGISTRY)
        task = asyncio.create_task(_heartbeat())
        return server, thread, task
    except Exception:
        logger.warning("Monitoring endpoint unavailable; continuing business service", exc_info=True)
        return None


async def stop(handle):
    if handle:
        server, thread, task = handle
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        try:
            if thread.is_alive():
                await asyncio.to_thread(server.shutdown)
            server.server_close()
            await asyncio.to_thread(thread.join, 2)
        except Exception:
            logger.warning("Could not stop monitoring endpoint", exc_info=True)


def cycle_completed():
    if enabled():
        _safe(lambda: PROGRESS.set(time.time()))
