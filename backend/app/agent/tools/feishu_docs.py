from app.agent.tools.base import ToolContext, ToolError, tool
from app.feishu.client import FeishuError
from app.sources import cloud, files
import json


@tool(
    "read_feishu_doc",
    "读取飞书链接的内容：新版文档正文、知识库节点、云空间上传的原始文件（/file/ 链接，Excel、Word、PDF）、"
    "妙记（/minutes/ 链接，会议录制的文字记录，带说话人），"
    "以及电子表格、多维表格的结构（表格再用 read_sheet_range 读数据）。以当前用户自己的权限读取。"
    "内容长时分段返回，按提示传 offset 继续。",
    {"url": {"type": "string", "description": "飞书 docx/wiki/sheets/base/board/file/minutes 链接"},
     "offset": {"type": "integer", "minimum": 0}},
    ["url"],
)
async def read_feishu_doc(ctx: ToolContext, args: dict) -> str:
    token = await ctx.feishu.user_token(ctx.user)
    if not token:
        raise ToolError("用户的飞书授权已过期，需要在 Relay 网页端重新登录一次后再试")
    try:
        data = await cloud.read_url(ctx.feishu, ctx.user, args["url"])
    except FeishuError as exc:
        raise ToolError(f"读取失败: {exc}") from exc
    content = data.get("content") if "content" in data else json.dumps(data, ensure_ascii=False)
    if not content.strip():
        return "（文档没有文字内容）"
    title = f"《{data['title']}》\n" if data.get("title") else ""
    return title + files.page(content, args.get("offset", 0))
