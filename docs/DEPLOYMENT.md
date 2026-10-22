# 部署与发布

可选的管理员服务器资源、任务运行与模型调用监控见 [系统性能监控](MONITORING.md)。使用独立 Compose 叠加文件启用，基础部署默认关闭，不新增业务表迁移。

## 公开仓库范围

本机发布源仅限 `/Users/ellis/Documents/CargoPPT/relay`，仓库固定为
`https://github.com/ciby9833/ai-relay.git`。不要在父目录 `CargoPPT` 执行添加或推送。

只发布源码、依赖清单、数据库迁移、配置模板和说明文档。以下内容不入库，也不应进入镜像：

- `.env` 及其他实际环境配置；模板 `.env.example` 只放空值或示例。
- Google 服务账号 JSON、私钥、证书私钥和 `secrets/`、`credentials/`。
- 数据库、导出文件、备份、日志、上传内容、真实账号验收记录。
- 本地依赖、缓存和编译产物。

`.gitignore` 防止误添加，`.dockerignore` 限制构建上下文。发布检查会检查暂存内容和
当前分支全部历史中的敏感路径、常见凭证格式，以及与本机 `.env`/服务账号凭证相同的内容。
这类扫描不能识别所有自定义格式的密钥，提交前仍需检查差异。

## 本机发布

首次启用本地保护（Git hooks 不会随 clone 自动启用）：

```bash
cd /Users/ellis/Documents/CargoPPT/relay
git config core.hooksPath .githooks
```

检查、提交并发布：

```bash
git status --short
git add .
python3 scripts/check_release.py
git diff --cached --stat
git diff --cached
# 确认内容之后提交；脚本不会自动添加或提交文件。
git commit -m "Describe the release"
./scripts/publish.sh
```

脚本仅允许此目录、此仓库及 `main` 分支，拒绝未提交的改动；推送不使用强制覆盖。
本地 hook 是防误操作措施，可被手动禁用，并非 GitHub 服务端访问控制。
服务器只需要拉取和部署，无需启用该本机发布 hook。

## 测试

```bash
# 独立数据库、模拟飞书，不读取生产 .env 或调用真实业务接口
# 此文件单独使用，不要与 compose.yml 合并。
docker compose -f compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yml down

# 生产镜像构建
# build 不启动或重启现有服务
docker compose build api web
```

生产后端仅安装运行时依赖；测试工具保留在 Dockerfile 的 `test` 构建阶段。
测试数据库只用临时内存文件系统，销毁测试容器后不会保留。

## 生产服务器首次启动

```bash
git clone https://github.com/ciby9833/ai-relay.git
cd ai-relay
cp .env.example .env
chmod 600 .env
# 编辑 .env，填好密钥、飞书与模型配置；不要将实际值提交到 Git。
```

必须设置：

```dotenv
ENV=production
DEV_LOGIN=false
SECRET_KEY=<用 openssl rand -hex 32 生成并安全保存>
POSTGRES_PASSWORD=<用 openssl rand -hex 16 生成并安全保存>
FRONTEND_URL=https://your-domain.example
FEISHU_REDIRECT_URI=https://your-domain.example/api/auth/feishu/callback
FEISHU_TENANT_KEY=<你的飞书租户>
```

还需填写 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 和至少一种模型凭证。
模型名称需按账号实际可用模型配置。使用 Vertex AI 时，在服务器安全放置服务账号 JSON，
设置 `GOOGLE_CREDENTIALS_FILE=./secrets/gcp.json`。Compose 将凭证只读挂载，不复制到镜像。
凭证须对容器中的 `relay` 用户可读；不要为解决权限问题开放给所有用户。

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8098/api/health
```

默认端口只绑定本机。由宿主机反向代理处理 HTTPS，转发到 `127.0.0.1:5173`；
不要公开数据库端口。HTTPS 反代必须关闭缓冲并为流式响应设置足够超时。
飞书重定向地址必须与后台配置完全一致。长连接事件不会广播给所有实例，
上线时避免本地和服务器同时使用同一飞书应用连接。

## 更新和恢复

更新前备份数据库、`.env` 和云凭证，备份仅保存在受控位置：

```bash
mkdir -p backups
chmod 700 backups
(umask 077; docker compose exec -T db pg_dump -U relay relay > "backups/relay-$(date +%Y%m%d-%H%M%S).sql")
git pull --ff-only
docker compose up -d --build
docker compose ps
```

API 启动时运行 Alembic 迁移，worker 和飞书进程等待 API 健康后启动。
`SECRET_KEY` 同时用于保存的 token 加密，不能随意替换；恢复时需一并恢复原密钥。
不要使用 `docker compose down -v` 清理生产环境，它会删除业务数据库卷。
涉及不可逆数据库迁移时，回退代码前需制定数据库恢复方案。

## 运行质量迁移 0016

本次增加 `assurance_events`，持久记录任务运行、完成核验、写入/业务结果回读、人工接管和管理员关闭复盘。验收来源、基线和最新回读继续保存在现有 `missions.criteria` JSONB，无需迁移旧任务内容。部署 API、worker 和前端应使用同一版本，先执行迁移再启动 worker。

上线后管理员在「运行质量」查看通知基线、质量事件采集起点及复盘覆盖率。质量统计不会伪造上线前的核验事件；通知可利用现有飞书卡片记录做前后周期比较。回滚代码可保留新增表；降级到 0015 会删除质量事件和人工复盘历史，需先备份。
