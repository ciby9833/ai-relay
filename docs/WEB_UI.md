# Web UI 与国际化

## 界面语言

Web 支持英语（en）、简体中文（zh）、印尼语（id）。第一次访问跟随浏览器向网页提供的系统首选语言：`navigator.languages[0]`，不可用时读 `navigator.language`。区域标签会归一化，如 `en-GB` → `en`、`zh-TW` → `zh`、`id-ID` → `id`；目前所有中文变体显示简体中文。不支持的首选语言回退英语。

登录页和「设置 → 语言 → 界面语言」都可以选择跟随系统或手动选择语言。手动选择即时生效，保存在当前浏览器的 `relay.ui-language`，刷新后保留，并同步到同源的其他标签页。跟随系统模式响应浏览器的 `languagechange` 事件。浏览器禁止存储时仍可以在当前页面切换。

界面语言和已有的 Relay 回复语言是独立设置。切换界面不修改用户的回复偏好、不发送消息，不清空输入框或邮件草稿。历史消息、邮件、任务正文、审批业务字段和原始服务端诊断保留原文；这是界面国际化，不是历史内容的自动翻译。

## 实现

- `frontend/src/i18n.ts`：语言解析、持久化、插值、英文单复数和服务端文案描述符。
- `frontend/src/useLocale.ts`：React 订阅语言变化，根组件刷新视图而不重建组件状态。
- `frontend/src/locales/messages.ts`：现有中文固定文案作为键，英语和印尼语译文集中维护。
- `frontend/src/locales/common.ts`：带参数的文案及新增控件，包含中英印三种文本。
- `frontend/src/format.ts`：使用 `Intl` 格式化日期、时间、相对时间和列表。
- 后端为跟进事项的标准操作提示及「Relay 在办」的固定标题/说明提供可选 `*_ui` 描述符；前端按当前语言即时渲染。原有字符串字段继续保留，兼容旧客户端；业务名称只作为参数传入，不翻译、不改写。

新增固定文案必须提供全部支持语言；避免在组件模块初始化时调用翻译函数并缓存结果。固定状态映射保存文案键，在渲染时翻译。

## 2026-10-16 UI / 交互检查

本轮按实际改动区域读取 Figma 的设计上下文与截图，范围包括：

| 区域 | 设计参考 | 核对内容 |
| --- | --- | --- |
| 侧栏 | [Desktop Sidebar](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=24-1677) | 导航层级、近期会话、选中状态 |
| 输入区 | [Chat input](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=24-1794) | 圆角输入容器、模型与发送操作的层级 |
| 表单 | [TextInput states](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=26-1764) | 默认、聚焦、禁用状态 |
| 确认操作 | [Inline confirmation](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=467-24714) | 操作对象、内容和确认按钮的位置关系 |
| 轮播与加载 | [Inline carousel](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=467-31022) | 桌面和移动端结构、浅深色、骨架屏参考 |

这份文件是通用组件与交互模式库；本轮沿用 Relay 已有品牌、图标和业务卡片，不将旅游/商品示例替换进业务页面。未宣称逐页验收整份 Figma 文件，也未验证所有原型连线。

已修复的问题：

1. 登录身份请求失败留下空白页：增加加载提示、错误提示及重试。
2. 历史会话仅有鼠标点击入口：改为原生按钮，保留独立删除入口和选中语义。
3. 设置抽屉缺少键盘焦点约束：使用模态 dialog，Tab/Shift+Tab 循环、Escape 关闭、关闭后恢复焦点。
4. 英语和印尼语文案较长时，状态标签、表单、操作按钮容易挤压：允许换行并检查 320/375px 宽度。
5. 窄屏默认展开看板挤占聊天空间：手机端默认收起，可手动展开，始终保留数量提示。
6. 同步/简报及设置保存失败缺少反馈：显示错误，并在保存期间阻止重复提交。

## 验证

前端：

```bash
cd frontend
npm ci
npx playwright install chromium
npm test
npm run build
```

Playwright 使用独立的 5180 端口和模拟 API，不发送真实邮件、不变更真实用户数据。覆盖三语和区域语言识别、英语回退、偏好保存、系统语言变化、跨标签页同步、存储不可用、切换时保留草稿、键盘导航、抽屉焦点、窄屏和深色布局。截图保存在被 Git 忽略的 `frontend/test-results/` 中。

后端：

```bash
docker compose -f compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yml down
```

本轮结果：16 项前端测试、76 项后端测试通过，TypeScript 与 Vite 生产构建通过。后端使用独立测试数据库。

变更保存在本地源码，未发布到线上。使用已构建的 Docker 服务时，需要按项目既有部署流程重新构建前端及 API，才能完整应用界面翻译与后端描述符。
