# Blog：数据库存储与发布

## 运行结构

- `/blog/`：React 公开文章列表。沿用 Relay 品牌与设计令牌，参考提供的 Claude Articles 截图，使用大标题、带封面的文章卡片；语言选择器在页脚。
- `GET /api/blog`：从数据库读取已发布文章元数据，不需要登录。正文不跟随界面语言自动翻译。
- `/blog/<slug>/`：FastAPI 读取原始 HTML，在正文前附加与首页共用的顶部导航（Relay、文章列表、打开 Relay）。导航通过 Shadow DOM 隔离样式，数据库原稿及正文样式均不改写。
- `/blog/<slug>/<asset-path>`：FastAPI 从数据库返回原始图片、视频、CSS 或字体。媒体支持正确 MIME、HEAD、ETag 和视频 Range 请求；缺失或草稿素材返回 404。先按 SHA-256 判断 304，Range 只从数据库取请求的字节段，不把整个视频读进内存。所有响应带 CSP（`script-src 'self'`）：文章与 App 同源，只允许站内脚本（共享导航），文章里的内联或外部脚本不会执行。
- `blog_posts` 表：标题、摘要、语言、可选发布日期、封面路径、草稿状态、内容版本摘要。
- `blog_assets` 表：原始 HTML 和全部本地素材的二进制数据（PostgreSQL `bytea`）、相对路径、MIME 和 SHA-256。

媒体真正存储在数据库中，不只是登记本地文件路径。服务请求时不读取前端文件系统，数据库备份包含文章及素材。前端的 `public/blog` 和生成 JSON 已移除；开发 Vite、Vite preview 和生产 Nginx 均把文章及资源请求代理到 API。

## 2026-10-20 导航与设计复核

首页和文章共用 `frontend/public/blog-navigation.js`。导航使用 `position: sticky; top: 0`，保留原文档流中的位置，滚动至文章底部仍可返回列表或打开 Relay。导航保持不透明背景和独立层级；通过 `ResizeObserver` 按实际高度更新根滚动容器的 `scroll-padding-top`，窄屏换行后，页内定位仍会避开导航。组件移除时恢复原滚动设置。

本次先读取 Figma 全文件页面目录，再选择与 Blog 相关的基础规范和组件；用户链接中的 `467:31022` 实际是 Inline carousel 页面。以下节点已读取设计上下文和截图：

| 参考 | 观察与 Blog 的对应方式 |
| --- | --- |
| [Color / Background Surface](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=467-20296) | 明暗模式分别定义背景层级。Blog 继续复用项目的 `--bg`、`--bg-sunken`、文字和边框变量；导航背景随主题变化，避免滚动正文透过导航影响阅读。 |
| [Typography](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=467-21506) | 字号、字重和行高按标题、正文、辅助信息分层。Blog 首页保留用户提供的 Articles 截图所要求的大衬线标题；原文章字体和行距保持原样。Figma 的应用内字体尺度不直接覆盖编辑型文章。 |
| [Layout / Border](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=467-21771) | 圆角按尺寸分级、边框保持轻量。Blog 延续已有卡片圆角和细边框，按钮与卡片有明确层级。 |
| [Inline card / Media card](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=467-24746) | 容器内区分标题、辅助说明、媒体和操作。Blog 卡片对应为类型/日期、标题/摘要、原稿封面、阅读入口；单篇文章不增加无实际内容的轮播控制。 |
| [Mobile / Navigation bar](https://www.figma.com/design/RRfNMUS8opt9NpLV0Ovdlu/?node-id=732-6077) | 窄屏保留明确导航入口、左右留白和独立操作区域。Blog 使用自身品牌与链接，在空间不足时允许换行；以实际导航高度调整滚动定位。 |

这份 Figma 是 Claude 应用组件库。上表是结合 Blog 场景的设计判断，不是文件中对营销站布局或吸顶行为的逐条规定；吸顶来自本次用户要求，首页卡片布局与页脚语言切换来自用户截图及先前要求。

验证：11 项 Blog 专项测试和 TypeScript/Vite 生产构建通过。覆盖首页/文章在 1440、375、320px 下滚动至中部和底部、导航不被正文覆盖、返回列表、页内定位不遮挡，以及桌面/手机明暗模式原文截图比较。截图比较屏蔽视频控件并使用字体回退；不代表外部字体加载质量检查。未部署到生产。

## 文章源文件

唯一维护入口是 `backend/content/blog/<slug>/`。第一篇文章位于 `relay-day`：

```text
backend/content/blog/relay-day/
  post.json
  index.html
  img/*.jpg
  relay-promo.mp4
```

文章只在 `backend/content/blog/<slug>/` 维护，不再保留其他副本（收到的原稿 `Relay-blog/` 和早期的 `docs/promo/` 已移除）。`backend/content/blog/_template/` 是新文章模板，以 `_` 或 `.` 开头的目录不会被导入。

输出 HTML 时，相对路径的 `og:image` 会被改写成基于 `FRONTEND_URL` 的完整地址（飞书等链接预览需要完整地址），数据库里的原稿不变。生产环境的 `FRONTEND_URL` 必须是对外的 https 域名。

`post.json` 例子：

```json
{
  "title": "文章标题",
  "description": "列表页摘要",
  "language": "zh-CN",
  "publishedAt": "2026-10-20",
  "cover": "img/cover.jpg",
  "draft": true
}
```

标题、摘要、语言、布尔值 `draft` 必填。`publishedAt` 在 `draft: false` 时必填；`cover` 可选。发布日期必须是真实日期，封面必须存在于文章目录。日期用于展示和排序，不代表定时发布。目录名仅使用小写英文字母、数字和连字符，发布后保持稳定。

HTML 中本地媒体应使用相对路径，例如 `img/board.jpg`。导入前会检查 HTML 的 `src`、`poster`、`srcset`、`link href` 对应的本地资源，缺失文件会阻止此次导入，不会替换数据库中的上一版。正文不会被重新排版或改写。

`index.html` 还要通过以下内容校验，任一不满足都会让 `--check` 和生产构建失败：

- `<html lang>` 与 `post.json` 的 `language` 一致；
- `<title>` 与 `post.json` 的 `title` 一致；
- 有非空的 `<meta name="description">`；
- 不引用外部 http(s) 资源（包括 `<link>`、`src`、`poster`、`srcset`、CSS 的 `url()` / `@import`）；普通的 `<a href>` 外链不受限；
- 不含 `<script>`、`on*=` 事件属性或 `javascript:` 链接；
- 写了 `og:image` 时，相对路径必须指向文章目录里的文件。文章包是经作者审核的 HTML，不提供公开上传/编辑接口。

## 发文章清单

动笔前：

1. 复制 `backend/content/blog/_template/` 为新目录，目录名就是 slug（小写字母、数字、连字符），发布后不再改。
2. 不要直接把 Artifact、宣传页或其他网页导出的 HTML 放进来。导出文件常带平台外壳、外部字体和与文章无关的标题；把内容搬进模板。

写的时候：

3. `post.json` 和 `index.html` 里的标题、摘要、语言保持一致；`draft` 先设为 `true`。
4. 只用系统字体栈。外部字体在国内经常加载失败，会让正文迟迟不显示。
5. 页面里不要再放 Relay 品牌行，顶部导航已经有了。
6. 素材全部放进文章目录，用相对路径。截图导出 JPG，宽度不超过 1600px；封面单独做一张 1200×630，选有实际界面内容的画面，不用片头卡或空白页。
7. 视频尽量压到 10MB 以内（目前视频存在 Git 和数据库里，体积会直接变成仓库和备份的负担）。正文写的时长与播放器显示一致。

发布前检查：

8. 截图、视频里没有内部模型名、调试信息、未翻译的界面 key、真实同事或客户数据；用演示数据时在文末注明是虚构的。
9. 说法不超过产品实际能力：安全相关写“需要你确认”这类可验证的机制，不写“保证不会”；上手步骤写清需要哪些授权。
10. 面向印尼同事的内容另建一篇（例如 `relay-day-id`，`language: "id"`），不要指望界面语言切换翻译正文。
11. 运行 `docker compose exec api python -m app.blog_import --check`，再导入到本地，打开 `/blog/` 和 `/blog/<slug>/`，在桌面和手机宽度、明暗两种模式下各看一遍。
12. 补上 `publishedAt`，把 `draft` 改为 `false`，与代码一起提交后按下面的生产流程发布。

## 生产发布

1. 将文章目录放入 `backend/content/blog/`，填写元数据，准备发布时设置 `"draft": false`。
2. 提交源码时包含文章 HTML、图片、视频、`post.json` 以及本次新增的迁移与导入代码。
3. 在服务器项目目录执行既有 Compose 发布流程：

   ```bash
   docker compose up -d --build api web
   ```

4. 生产镜像构建时先校验文章包，缺失图片等问题会直接阻止构建。API 容器启动命令先执行 `alembic upgrade head`（包含 `0013_blog`），随后应用启动时执行导入。启动导入失败只记录日志（`relay.blog`），API 照常启动并继续提供数据库里的上一版文章。后端生产镜像已包含 `content/`；`.dockerignore` 明确保留文章 `post.json`。
5. 在实际网站域名检查 `/api/blog`、`/blog/`、`/blog/relay-day/`，并检查图片和视频能正常读取。

无需在生产数据库手工执行 INSERT 或另外复制素材到 Nginx。导入以事务执行并使用 PostgreSQL advisory lock，支持 API 多副本；没有变化的文章不重复插入、不改变更新时间。内容变化时更新文章和素材，已移除的素材同步删除。

首次上线会创建表并导入；后续部署更新同一 slug；设为草稿或移除目录后重新部署，该文章及其素材的公开访问都返回 404。移除目录会将数据库记录标记为草稿，保留数据用于备份；恢复目录可重新发布。导入是整个版本目录的同步，维护时不要使用只包含部分正式文章的目录覆盖完整文章包。

## 本地开发

启动项目：

```bash
docker compose -f compose.yml -f compose.dev.yml up -d --build api web
```

文章/元数据修改后，运行：

```bash
docker compose exec api python -m app.blog_import --check
docker compose exec api python -m app.blog_import
```

`--check` 只校验文件，不写数据库。导入成功后刷新网页即可，无需重新构建前端。仅启动 Vite 时，也需要 API 和数据库运行；Vite 默认代理 `localhost:8098`，容器开发配置代理 `api:8000`。

前端配置发生变更时重启运行中的开发服务：

```bash
docker compose restart web
```

本轮修复中实际观察到：旧的 5173 开发服务把 JPG 请求回退成了 HTML，造成图片损坏。重启并使用统一 API 代理后，实际入口返回 `image/jpeg`，视频 Range 请求返回 `206 video/mp4`。

## 验证

```bash
cd frontend
npm run build
npm test -- tests/blog.spec.ts
```

前端专项测试使用模拟 API，覆盖卡片布局、页脚语言切换、空状态/失败重试、原文保留和桌面/手机明暗模式。文章截图比较统一使用字体回退并屏蔽原生视频控件，避免外部字体网络造成随机差异；线上字体链接保持原样。

从仓库根目录运行后端测试：

```bash
docker compose -f compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yml down
```

`backend/tests/test_blog.py` 使用独立测试数据库，覆盖首次/重复导入、逐字节还原、移除源文件后仍可从数据库读取、MIME、ETag、HEAD、Range、草稿隐藏、下线/恢复及无效文章包不覆盖已发布内容。不要针对业务数据库设置 `RUN_DB_TESTS=1`。
