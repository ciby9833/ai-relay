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

import httpx
import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from app.api.feishu_events import dispatch_event
from app.proactive.callbacks import respond
from app.config import get_settings
from app.feishu.client import FeishuClient

logger = logging.getLogger("relay.feishu")



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
        future = asyncio.run_coroutine_threadsafe(respond(feishu, operator, value, message_id), loop)
        try:
            return P2CardActionTriggerResponse(future.result(timeout=2.8))
        except Exception:
            logger.exception("处理卡片按钮失败")
            return P2CardActionTriggerResponse({"toast": {"type": "error", "content": "处理失败，请稍后再试"}})

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
