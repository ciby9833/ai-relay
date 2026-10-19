"""飞书长连接：python -m app.feishu.longconn

不需要公网地址。lark-oapi 的长连接客户端会在主线程里跑它自己的事件循环，
所以收到的事件转交给后台线程里的另一个事件循环处理，回调本身立即返回。
"""

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout

import httpx
import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from app.api.feishu_events import dispatch_event
from app.proactive.callbacks import deferred_update, handle_card_action
from app.config import get_settings
from app.feishu.client import FeishuClient

logger = logging.getLogger("relay.feishu")

CARD_LIMIT = 28 * 1024  # 回调响应里的卡片上限约 30KB
CALLBACK_WAIT_SECONDS = 2.2


def _log_failure(future: Future) -> None:
    if future.exception():
        logger.error("处理飞书事件失败", exc_info=future.exception())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, name="relay-events", daemon=True).start()
    feishu = FeishuClient(settings, httpx.AsyncClient(timeout=30))

    def on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        body = json.loads(lark.JSON.marshal(data))
        future = asyncio.run_coroutine_threadsafe(dispatch_event(feishu, body), loop)
        future.add_done_callback(_log_failure)

    def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        event = data.event
        operator = event.operator.open_id if event.operator else None
        value = (event.action.value if event.action else None) or {}
        if not operator or "relay" not in value:
            return P2CardActionTriggerResponse({})
        message_id = event.context.open_message_id if event.context else None
        started = time.monotonic()
        logger.info("收到卡片回调 operator=%s relay=%s message=%s", operator, value.get("relay"), message_id)
        future = asyncio.run_coroutine_threadsafe(handle_card_action(feishu, operator, value, message_id), loop)
        try:
            # 飞书要求 3 秒内响应：多数操作（批准、接受会议）1~2 秒能完成，就直接把新卡片放进响应
            result = future.result(timeout=CALLBACK_WAIT_SECONDS)
        except FutureTimeout:
            logger.info("卡片回调 %.1fs 内没处理完，先回 toast，处理完再更新卡片", time.monotonic() - started)
            # 来不及（例如起草要调模型）：先响应，完成后再更新卡片
            def later(done: Future) -> None:
                if not done.exception():
                    asyncio.run_coroutine_threadsafe(deferred_update(feishu, message_id, done.result()), loop)
            future.add_done_callback(later)
            future.add_done_callback(_log_failure)
            return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "收到，正在处理…"}})
        except Exception:
            logger.exception("处理卡片按钮失败")
            return P2CardActionTriggerResponse({"toast": {"type": "error", "content": "处理失败，请稍后再试"}})
        if result is None:
            logger.warning("卡片回调没有对应的用户或操作 operator=%s relay=%s", operator, value.get("relay"))
            return P2CardActionTriggerResponse({})
        response: dict = {"toast": {"type": "success" if result["ok"] else "error", "content": (result["message"] or "已处理")[:60]}}
        if result["card"]:
            size = len(json.dumps(result["card"], ensure_ascii=False).encode())
            if size <= CARD_LIMIT:
                response["card"] = {"type": "raw", "data": result["card"]}
            else:
                # 卡片太大放不进回调响应（飞书会报 200671）：只回 toast，再单独更新卡片
                asyncio.run_coroutine_threadsafe(deferred_update(feishu, message_id, result), loop)
        logger.info("卡片回调处理完 %.1fs ok=%s card=%s", time.monotonic() - started, result["ok"], "card" in response)
        if not result["ok"] and result["message"] and len(result["message"]) > 60:
            # 原因较长时另发一条完整说明
            asyncio.run_coroutine_threadsafe(feishu.send_text(result["open_id"], result["message"]), loop)
        return P2CardActionTriggerResponse(response)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )
    client = lark.ws.Client(
        settings.feishu_app_id,
        settings.feishu_app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    logger.info("正在建立飞书长连接")
    client.start()


if __name__ == "__main__":
    main()
