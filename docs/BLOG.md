# Blog：数据库存储与发布

第二篇、第三篇及后续文章都按以下顺序操作：[准备文章与素材](#准备文章与素材) → [本地预览](#本地预览) → [生产发布](#生产发布)。下文统一使用 `relay-follow-up` 作为新文章 slug 示例；每篇新文章换成自己的目录名。

| 阶段 | 在哪里执行 | 结果 |
| --- | --- | --- |
| 准备内容 | 本地项目目录 | 创建 HTML、元数据和素材文件 |
| 本地预览 | 本机开发容器和本地数据库 | 导入后在 localhost 查看，不会自动发布生产 |
| 生产发布 | 生产服务器项目目录 | 构建已提交的文章版本并导入生产数据库 |

## 运行结构

- `/blog/`：React 公开文章列表。沿用 Relay 品牌与设计令牌，参考提供的 Claude Articles 截图，使用大标题、带封面的文章卡片；语言选择器在页脚。
- `GET /api/blog`：从数据库读取已发布文章元数据，不需要登录。正文不跟随界面语言自动翻译。
- `/blog/<slug>/`：FastAPI 读取原始 HTML，在正文前附加与首页共用的顶部导航（Relay、文章列表、打开 Relay）。导航通过 Shadow DOM 隔离样式，数据库原稿及正文样式均不改写。
- 文章目录：同一个共用脚本里的 `<relay-blog-toc>` 读取正文的 `<h2>` 自动生成，文章不用自己写。至少 4 个 `<h2>` 才显示；正文左侧放得下时固定在左侧并高亮当前章节，放不下时（手机、窄窗口）变成导航下方可展开的“目录”栏。没有 id 的标题在页面里自动补 `section-N`，数据库原稿不变。所以写文章时，每个大章节用 `<h2>`，标题写得短一些。
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

## 准备文章与素材

### 1. 从模板新建文章目录（本地）

在本地项目根目录执行。先选择一个尚未使用的 slug；不要把模板复制到已有文章目录中。以下示例创建第二篇，第三篇及以后换一个新 slug，其他步骤相同：

```bash
cd /Users/ellis/Documents/CargoPPT/relay
cp -R backend/content/blog/_template backend/content/blog/relay-follow-up
mkdir -p backend/content/blog/relay-follow-up/img
mkdir -p backend/content/blog/relay-follow-up/video
```

完成后的目录结构：

```text
backend/content/blog/
  _template/                     模板，不参与导入
  relay-day/                     第一篇，继续保留
  relay-follow-up/                新文章，目录名决定访问地址
    post.json                    标题、摘要、语言、日期、封面、草稿状态
    index.html                   正文及文章自身的 CSS
    img/
      cover.jpg                  首页卡片与分享封面
      step-1.jpg                 正文截图
      video-poster.jpg           视频播放前的封面
    video/
      demo.mp4                   视频
```

图片和视频放在各自文章目录中，不需要复制到前端 `public/` 或 Nginx。子目录名称可以自行组织，只要 HTML 中的相对路径与文件位置一致。

### 2. 填写元数据与正文

编辑新目录中的 `post.json`，按照上方示例填写标题、摘要、语言和封面，写作阶段保持 `draft: true`。模板日期只是占位值，发布前替换为实际发布日期。`publishedAt` 仅用于展示和排序；即使填写未来日期，`draft: false` 的文章导入后也会立即公开。

编辑 `index.html`：`<title>` 必须与 JSON 标题一致，`<html lang>` 必须与 `language` 一致，填写非空的 `<meta name="description">`，建议与 JSON 摘要保持一致。公共顶部导航会自动加入，不需要在正文重复放 Relay 品牌行。

在 `<head>` 中设置分享封面：

```html
<meta property="og:image" content="img/cover.jpg">
```

在正文中用相对路径插入图片和视频：

```html
<img src="img/step-1.jpg" alt="操作步骤说明">

<video controls preload="metadata" poster="img/video-poster.jpg">
  <source src="video/demo.mp4" type="video/mp4">
</video>
```

写作与素材检查清单：

- 不要直接把 Artifact、宣传页或其他网页导出的 HTML 放进来。导出文件常带平台外壳、外部字体和无关标题；把内容搬进模板。
- 使用系统字体栈，不引用外部字体、样式或媒体，不加入脚本、事件属性或 `javascript:` 链接。普通正文外链可以保留。
- 截图导出 JPG，建议宽度不超过 1600px；封面建议单独做一张 1200×630，选有实际界面内容的画面，不用片头卡或空白页。
- 视频尽量压到 10MB 以内，正文写的时长与播放器显示一致。素材存在 Git 和数据库中，体积直接影响仓库、镜像和备份大小；尺寸与体积建议目前需人工检查。
- 截图、视频里没有内部模型名、调试信息、未翻译的界面 key、真实同事或客户数据；用演示数据时在文末注明是虚构的。
- 说法不超过产品实际能力：安全相关写“需要你确认”这类可验证的机制，不写“保证不会”；上手步骤写清需要哪些授权。
- 面向印尼同事的内容另建一篇（例如 `relay-follow-up-id`，`language: "id"`）；界面语言切换不会翻译正文。

## 本地预览

本节命令只在本机项目根目录执行，使用本地开发配置和本地数据库，不在生产服务器执行。

### 1. 启动开发服务

```bash
cd /Users/ellis/Documents/CargoPPT/relay
docker compose -f compose.yml -f compose.dev.yml up -d --build api web
```

开发配置将本地 `backend/` 挂载到 API 容器，导入器可以直接读取刚编辑的文章文件。仅启动 Vite 不够，仍需要 API 和数据库运行；Vite 默认代理 `localhost:8098`，容器内开发配置代理 `api:8000`。

### 2. 校验文章包

```bash
docker compose -f compose.yml -f compose.dev.yml exec api python -m app.blog_import --check
```

`--check` 检查整个内容目录，包括草稿，但不写数据库。出现错误时按提示修复标题、语言、日期或资源路径，检查通过后再导入。

### 3. 开启本地可见状态并导入

目前没有独立的草稿预览入口。`draft: true` 的文章不会出现在首页，直接访问正文或素材也会返回 404。

要从本地网站预览，将新文章的 `draft` 改为 `false`，填好有效的 `publishedAt`，然后依次执行：

```bash
docker compose -f compose.yml -f compose.dev.yml exec api python -m app.blog_import --check
docker compose -f compose.yml -f compose.dev.yml exec api python -m app.blog_import
```

检查命令成功后再执行导入。导入会把 HTML、图片和视频一起写入本地数据库，不会自动同步生产数据库。

### 4. 打开页面验收并迭代

默认端口下打开：

- [本地 Blog 首页](http://localhost:5173/blog/)：新文章卡片、标题、日期、摘要、封面正确。
- [新文章正文](http://localhost:5173/blog/relay-follow-up/)：图片清晰、视频能播放和拖动进度、顶部导航吸顶及返回列表正常。
- 桌面与手机宽度、浅色与深色模式都检查一遍；界面语言切换位于首页页脚，正文仍保留自身语言。

如果本地配置了其他 `WEB_PORT`，使用对应端口；示例 URL 中的 `relay-follow-up` 换成实际 slug。

每次修改正文、元数据、图片或视频后，重复步骤 3 的检查与导入，再刷新浏览器。网页读取的是数据库，单纯保存文件不会自动更新已导入内容；内容更新无需重新构建前端。

如果预览后暂时不准备上线，提交前将 `draft` 改回 `true`，再导入一次可让本地也恢复为草稿。仅在本地设置 `draft: false` 不会触发生产发布，但它随代码部署后会公开。

## 生产发布

本节的构建命令在生产服务器项目根目录执行，使用 `compose.yml`，不叠加 `compose.dev.yml`。生产内容来自构建镜像中的已提交文件，不使用本地开发目录挂载。

### 1. 本地完成发布准备

1. 按本地预览流程验收文章。
2. 确认该文章 `draft: false`，日期为实际发布日期，`cover` 和 HTML 中的图片、视频路径均有效；再运行一次 `--check`。
3. 检查并提交新文章的完整目录，包括 `post.json`、`index.html`、图片和视频，然后推送至项目实际使用的发布分支。
4. 保留第一篇及其他仍需发布的文章目录。导入是对整个内容目录的同步，不能用只包含第二篇的目录替换完整文章集合。

日常新增第二篇、第三篇只需增加内容目录，不需要新增数据库迁移或修改业务代码。

### 2. 在生产服务器构建与启动

进入服务器的实际项目目录，按项目既有流程拉取或检出包含新文章的已提交版本。确认生产 `FRONTEND_URL` 是网站对外的 HTTPS 地址，再执行：

```bash
docker compose up -d --build api web
```

发布过程中自动执行：

1. 后端镜像包含完整 `content/`，构建时先校验文章包；缺失图片等校验错误会阻止构建。
2. API 容器启动命令执行 `alembic upgrade head`，首次部署包含 Blog 的 `0013_blog` 表结构迁移。
3. API 启动导入文章及素材到生产数据库；已有文章按 slug 更新，无变化的文章跳过。
4. Nginx 将首页交给前端，将文章正文与媒体请求转发给 API，从数据库读取。

无需手工执行 INSERT，也无需额外把图片或视频复制到 Nginx。生产文章打包在镜像里，只重启旧容器或在旧容器里运行导入命令，不会得到尚未构建进去的新文章。

### 3. 验证生产结果

在实际网站域名下检查以下路径，替换为本篇实际 slug：

- `/api/blog`：包含新文章的标题、日期、链接和封面。
- `/blog/`：出现新文章卡片，点击可进入正文。
- `/blog/relay-follow-up/`：正文排版、图片、视频、吸顶导航正常。
- 用实际文章链接检查分享预览，确认封面地址使用生产域名；第三方平台可能缓存旧预览。

如果未出现新文章，在生产服务器查看：

```bash
docker compose logs --tail=200 api
```

启动导入失败会记录 `relay.blog` 日志；API 继续启动并提供数据库上一版文章，因此网站能打开不代表新文章已成功发布。先确认部署版本、`draft` 状态和日志中的错误，修复后重新构建发布。

## 已发布文章更新与下线

- 更新：保持原 slug，修改同一目录，完成本地检查、导入预览、提交及生产发布。导入事务会一起更新文章元数据与素材；已移除的素材同步删除。
- 下线：将 `draft` 改为 `true` 后重新发布，文章及其素材公开访问均返回 404。也可以移除该文章目录后发布；数据库会将其标记为草稿并保留素材用于备份。
- 恢复：恢复完整文章目录并设置 `draft: false`，按同一流程重新发布。

导入以事务执行并使用 PostgreSQL advisory lock，支持 API 多副本；没有变化的文章不重复插入、不改变更新时间。每次导入都以完整内容目录为准。

## 验证

```bash
cd frontend
npm run build
npm test -- tests/blog.spec.ts
```

前端专项测试使用模拟 API，覆盖卡片布局、页脚语言切换、空状态/失败重试、原文保留和桌面/手机明暗模式。文章截图比较屏蔽原生视频控件，并阻止外部 Google Fonts 请求以避免网络差异。当前文章使用系统字体栈，首页使用随前端打包的 Source Serif 4，不依赖外部字体服务。

从仓库根目录运行后端测试：

```bash
docker compose -f compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yml down
```

`backend/tests/test_blog.py` 使用独立测试数据库，覆盖首次/重复导入、逐字节还原、移除源文件后仍可从数据库读取、MIME、ETag、HEAD、Range、草稿隐藏、下线/恢复及无效文章包不覆盖已发布内容。不要针对业务数据库设置 `RUN_DB_TESTS=1`。
