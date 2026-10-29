Relay 对话工作台 · 交互原型与研发交接 V1
2026-10-29

开始体验
1. 解压整个文件夹，使用浏览器打开 index.html。无需安装、联网或账号。
2. 顶部可切换手机预览、即时提醒、加载、空状态、同步失败、会后行动。
3. 点击“研发说明”进入 handoff.html；“重置”恢复演示状态。
4. 浏览器若限制 file:// 本地存储，刷新后的状态可能不保留。

建议体验
会议 → 质量改进会 → 相关材料 → Jose 私聊 → 就资料提问。
待处理 → 版本验收 → 已处理 → 提醒前已完成 → 进展 → 撤销。
待处理 → 新功能申请组 → 查看一张申请 → 确认 → 其他申请保留。
会议 → 印尼重构同步会 → 回复邀请。
会后行动场景 → 从纪要加入待处理。

交付内容
index.html：完整离线可交互原型（CSS、JS、图标全部内嵌）。
handoff.html：产品决策、交互约定、通知分层、响应式、组件与接口建议、验收及参考来源。
design-tokens.json：设计变量基线。
interaction-contract.json：建议的数据与交互契约。
validation.html / validation-results.json：实际验证记录与范围。
desktop-*.png / mobile-preview.png：评审画面。
src/：可编辑 HTML 模板、CSS 和 JS。
build.py：从 src 重新生成 index.html（Python 3，无额外依赖）。
tests/：可复现的 Playwright 检查脚本。

研发使用
先阅读 handoff.html 的第 8、9 节，再结合现有 API 与组件拆分实施。
本交付未读取 Relay 仓库，不应把建议字段或接口当作现存实现。
修改 src 后运行：python3 build.py
如需本地 HTTP 预览：python3 -m http.server 8080 --bind 127.0.0.1
打开 http://127.0.0.1:8080/index.html

运行验证（需 Node.js，安装依赖时联网）
npm install --no-save playwright
npx playwright install chromium
node tests/verify.cjs
node tests/extra-check.cjs
若已有兼容浏览器，可用 CHROMIUM_EXECUTABLE 环境变量指定可执行文件。

边界
材料摘录及审批详情为演示编写，不是实际业务原文。
没有连接真实模型、日历、消息服务或生产数据库；不会发送消息或执行审批。
普通状态变化可在本地撤销；真实外部操作必须遵循来源系统的能力。
首次展示的数据按固定示例时间呈现，不是实时日程。
