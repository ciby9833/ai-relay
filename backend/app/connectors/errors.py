"""工具出错时的统一错误码：说清楚是什么原因、该谁去处理。

模型和界面都按错误码说明，不再靠提示词提醒“不要笼统说没有权限”。
"""

from dataclasses import dataclass

from app.feishu.client import FeishuAuthError, FeishuError


@dataclass(frozen=True)
class ErrorCode:
    code: str
    meaning: str  # 是什么原因
    who: str  # 该谁处理、怎么处理（直接给用户看的说法）


ERRORS: dict[str, ErrorCode] = {e.code: e for e in [
    ErrorCode("not_connected", "这个数据源还没有接入", "请管理员在“工作区设置”里接入，或在设置里连接自己的账号"),
    ErrorCode("needs_reauth", "他的授权过期了，或者授权里缺这一项", "请重新登录一次（授权页里同意即可）"),
    ErrorCode("app_scope", "应用还没有开通这项权限", "需要管理员在飞书后台为 Relay 应用开通对应权限并发布，然后他重新登录一次"),
    ErrorCode("no_access", "他本人对这份资源没有权限（文件、表格、审批……）", "需要找资源的所有者给他开通"),
    ErrorCode("not_found", "找不到这份资源", "请核对链接或编号"),
    ErrorCode("invalid_input", "参数不对", "按工具的要求重新提供"),
    ErrorCode("unsupported", "Relay 还没有这个功能", "如实告诉他还不支持，不要说成没有权限"),
    ErrorCode("conflict", "状态已经变了（别人刚处理过、文件被改过、版本对不上）", "刷新后再看是否还需要做"),
    ErrorCode("offline", "他的设备（Mac 客户端）现在不在线", "打开 Relay 客户端后再试"),
    ErrorCode("limit", "这一轮同一类查找已经查了好几次", "停下来，告诉他查过哪些地方，问他资料在哪"),
    ErrorCode("precondition", "前置条件不满足", "按说明补齐条件后再试"),
    ErrorCode("upstream", "外部服务暂时出错", "稍后再试"),
    ErrorCode("internal", "Relay 内部错误", "稍后再试；一直出错请联系管理员"),
]}

# 飞书接口的错误码 → 统一错误码。只收已经在各数据源里核实过的码（app/sources/sheets.py、bitable.py），
# 其他码按报错文字判断，判断不了归为 upstream，不猜。
FEISHU_CODES = {
    99991679: "app_scope",
    1061004: "no_access", 91403: "no_access", 1310213: "no_access", 1310217: "no_access", 1254302: "no_access", 1254303: "no_access",
    1310214: "not_found", 1310211: "not_found",
}


class ToolFailure(Exception):
    """带错误码的工具失败。工具里抛 ToolError 时也可以带 code（见 app/agent/tools/base.py）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code if code in ERRORS else "precondition"


def classify(exc: BaseException) -> str:
    """把异常归到统一错误码。工具把底层错误包了一层时（raise ToolError(...) from exc），按根因判断。"""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in ERRORS:
        return code
    cause = exc.__cause__ or exc.__context__
    if not isinstance(exc, FeishuError) and isinstance(cause, FeishuError):
        root = classify(cause)
        if root != "upstream":
            return root
    if isinstance(exc, FeishuAuthError):
        return "needs_reauth"
    if isinstance(exc, FeishuError):
        text = str(exc)
        if exc.code in FEISHU_CODES:
            return FEISHU_CODES[exc.code]
        if "还没有接入飞书" in text:
            return "not_connected"
        if "user identity" in text:
            return "needs_reauth"
        if "required privileges" in text or "scope" in text.lower():
            return "app_scope"
        if exc.code in (403,) or "permission" in text.lower() or "forbidden" in text.lower():
            return "no_access"
        if exc.code in (404,) or "not found" in text.lower():
            return "not_found"
        return "upstream"
    return "precondition"


def error_result(tool: str, code: str, message: str) -> dict:
    """出错时的统一结果：错误码、原因、该谁处理。"""
    entry = ERRORS.get(code, ERRORS["precondition"])
    return {"ok": False, "tool": tool, "error": {"code": entry.code, "meaning": entry.meaning, "who": entry.who}, "message": message}
