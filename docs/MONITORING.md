# 管理员系统性能

入口：管理员侧栏「运行质量」→「系统性能」。普通用户看不到入口，后端对每次查询独立检查数据库中的 `is_admin`，未登录返回 401、非管理员返回 403。检查在读取缓存之前执行，管理员被降权后不能继续读取已缓存的数据；响应设置 `Cache-Control: no-store`。

## 架构与范围

适用环境为 **Linux 单机、rootful Docker Compose、模型使用外部 API**。本机 Docker Desktop 的容器运行在 Linux 虚拟机中，其数据不能当作生产服务器或 macOS 整机数据；rootless Docker、自定义数据目录需要单独适配采集挂载。

原有 `web / api / worker / feishu / db` 职责、调度次序、数据库结构不变。独立叠加文件 `compose.monitoring.yml` 增加：

| 组件 | 用途 |
| --- | --- |
| Node Exporter | 宿主机 CPU、内存、Swap、文件系统、磁盘、OOM |
| cAdvisor | Compose 服务容器的 CPU、内存工作集、网络流量、最近采样 |
| Prometheus | 每 30 秒采样；历史最多 15 天、存储块保留上限 2 GB |

三个 Python 进程各自增加一个内部 9101 指标端口及事件循环心跳；模型、工具、对话的计数计时只写进程内存，没有额外网络调用、业务数据库写入或模型请求。Prometheus 从各进程采样，指标不包含用户、任务、提示词、文档或错误原文。GPU 未启用采集，页面明确显示「未配置」，不推断服务器是否有 GPU。

Node Exporter 在桥接网络中运行，关闭会误读容器网络命名空间的采集项。页面网络图来自五个**业务容器流量之和**，包含容器间通信，不等于宿主机外网带宽或云账单流量。

API 提供固定的只读接口 `GET /api/admin/performance?window=1h|24h|7d`。不接受用户指定查询表达式或目标 URL。查询并发合并并缓存 15 秒；Prometheus 请求超时 5 秒，任务到期统计超时 2 秒。鉴权后先释放数据库连接，再等待监控查询或缓存锁，避免慢查询持续占用业务连接池。趋势窗口最多约 337 个时间点／序列。浏览器每 30 秒刷新，离开页面取消请求并停止轮询，后台标签页暂停刷新。

监控开关默认关闭。业务服务不依赖监控服务启动；缺少监控 Python 依赖、采集端口绑定失败、Prometheus 掉线、统计记录失败都不会替换业务结果。缺少依赖时记录警告并停用进程内采集，业务仍可启动。性能页面独立显示未启用、部分不可用、采集过期或无样本；不把缺失值补成 0。监控本身仍有少量 CPU、内存和磁盘开销，不承诺资源开销为零。

## 启用

先按 [部署说明](DEPLOYMENT.md) 完成原有配置。默认 Compose 项目名为 `relay`；如使用 `-p` 或 `COMPOSE_PROJECT_NAME` 改名，需同步修改 `monitoring/prometheus.yml` 的 cAdvisor 项目名过滤条件。

```bash
docker compose -f compose.yml -f compose.monitoring.yml config --quiet
docker compose -f compose.yml -f compose.monitoring.yml up -d --build
docker compose -f compose.yml -f compose.monitoring.yml ps
```

这会部署新版本并按需重建现有应用容器，需等待正在执行的工作完成并安排正常发布窗口，不能视为零停机开关。开发环境应保留覆盖文件，使用 `-f compose.yml -f compose.dev.yml -f compose.monitoring.yml`。后续更新、查看日志仍使用同一组 `-f` 参数，避免误以为可选服务不存在。无需新增业务数据库迁移；应用本身原有启动迁移流程不变。

采集组件不发布宿主机端口，Nginx 只转发已有管理员 API。**不要**将 Prometheus、cAdvisor、Node Exporter 或业务指标端口公开到互联网，也不要把 Docker socket 挂入业务 API。

cAdvisor 按其官方 Linux 部署方式使用特权容器、`/dev/kmsg` 和宿主机只读挂载。这些权限仅属于独立采集组件；`/var/run` 下的 Docker socket 即使只读挂载也不能视为只读 API 权限。仅在可信服务器部署固定版本镜像；已有企业采集系统时，可以复用采集系统并适配固定查询，而无需再部署 cAdvisor。

预设上限：Prometheus 512 MiB / 0.5 CPU，Node Exporter 128 MiB / 0.25 CPU，cAdvisor 256 MiB / 0.5 CPU。这些是限制，不是实际占用或预留值。页面也显示采集组件的 CPU、内存；依据实际样本数调整。Prometheus 2 GB 是存储块保留策略，**不是整个卷的硬配额**，WAL、head 和压缩过程需要额外空间，建议至少预留 5 GB 可用磁盘。

首次启用通常需要几个采样周期才能显示速率；历史从启用时开始。性能图不回填过去的虚构样本。

## 指标口径

- 主机 CPU 为逻辑核的平均忙碌率，另显示各核、1 分钟负载及 I/O wait。容器 CPU 单位为占用核数，1.0 表示一个逻辑核。
- 内存使用率按 `1 - MemAvailable / MemTotal`；容器内存为工作集，二者不能直接相加比较。Swap 总量为 0 表示未配置 Swap。
- 磁盘展示主要挂载点可用／总容量、可用空间趋势及主机块设备读写速率。排除临时、overlay、loop 文件系统。读写和延迟按所选设备展示，不把逻辑盘与物理盘相加；设备应结合服务器磁盘布局选择。文件系统读取失败时隐藏对应容量，不能显示成 0 可用；无 I/O 时延迟为未知而不是 0。
- 速率使用 2 分钟窗口。P95 使用 5 分钟窗口；调用、tokens、OOM 增量使用 1 小时窗口，Prometheus 插值可能产生小数，属于估算。已配置模型供应商的计数器启动时建立零基线；首次抓取前的调用仍无法追溯，不可用这些估算替代精确账单。
- 「正在处理的对话轮次」覆盖 Web、飞书、定时和长期任务进入 Agent 主循环的轮次。「正在调用模型」也覆盖后台分类、简报与核验，不包含 embedding 请求。两者有包含关系，不能相加当作 Agent 总数。
- 任一业务进程采集缺失或心跳超过 45 秒时，全局执行总数显示 `—`。指标抓取由独立线程提供，事件循环心跳能帮助发现「端口可达但业务循环停止推进」。
- 「到期待领取／检查」只读查询数据库里的 `next_run_at <= now`：定时任务要求启用；长期任务要求 `active / waiting`，包含等待超时。普通等回复、等确认、未来执行、已领取待执行、执行中、尚未发现的事件不算在这个数字里。因此它不是完整消息队列深度，也不会为了监控去拉飞书或唤醒任务。
- worker 最近一轮结束时间只表示流程走完，流程里某个任务仍可能失败。心跳／容器近期可见不代表飞书连接、外部 API 或业务结果健康。
- 模型指标按供应商汇总；首段文字时间只统计非空文本，工具专用响应不计。调用失败包含超时和 429，取消单独记录、不计失败。tokens 为供应商提供的输入／输出量，不作计费推算。
- 宿主机／容器采集失败时当前资源值隐藏；历史图保留缺口。额外检查 Node Exporter 各子采集器是否成功，防止 HTTP 抓取成功但指标读取失败时沿用旧速率；容器聚合前排除超过 90 秒未见的容器。模型历史统计可能来自部分进程，请同时查看采集状态。

## 验证与故障定位

1. 普通账号无入口，直接访问性能接口返回 403；未登录返回 401。
2. 管理员页面检查五个采集目标 `node / cadvisor / api / worker / feishu`；采集可达只代表指标抓取成功。
3. 在服务器对照 `free`、`df`、`docker stats --no-stream`，注意内存工作集／缓存及 CPU 核数口径。不能用本机 Docker Desktop 的数字替代生产验收。
4. 执行一轮普通对话及一个已有后台任务，观察各进程执行数、模型耗时和 worker 推进时间；无需为监控创建真实业务写入操作。
5. 在测试环境停止 Prometheus 或任一采集器：管理员页面显示不可用／缺失，聊天、任务、飞书入口仍按原流程工作。数据库故障本身仍会影响原业务；本模块不改变其依赖关系。

仓库测试覆盖真实登录凭证下的管理员降权与缓存权限、未启用、缺少监控依赖时业务模块仍可加载、端口重复启停、查询失败、采集过期、缓存合并、非有限数值、流式输出／异常／取消透传、到期统计不修改任务，以及三语言和移动端展示。

`backend/scripts/monitoring_query_cases.py` 使用实际接口的 PromQL 生成数值用例，可在独立测试镜像中生成后交给 `promtool test rules`。覆盖 CPU／内存比例、磁盘分设备统计、真实满盘与文件系统读取失败、过期容器、心跳过期、首次错误增量与计数器重置。数值测试不能替代生产 Linux 服务器上的挂载与实际读数验收。

### Vite 连接 API 被拒绝

`/api/auth/me` 的 `ECONNREFUSED ...:8000` 表示代理未连到 API，需先查看 `docker compose -f compose.yml -f compose.dev.yml logs api`。本次确认的原因是旧开发镜像通过源码挂载加载了新代码，但缺少新增的 `prometheus-client` 依赖，导致 API 导入阶段退出。现已改为缺少依赖时跳过监控，开发版 web 也等待 API 健康后再启动。

要实际启用进程指标，仍应在发布时用上述 `up -d --build` 重建镜像，保留所需开发／监控覆盖文件。生产 Nginx 已通过 Docker DNS 定期解析 API，API 容器 IP 改变后不再持续转发到旧地址；重建期间 API 本身短暂不可用仍需按正常发布处理。

## 停用与回退

```bash
# 只停止三个采集组件；不停止业务服务，不删除卷
docker compose -f compose.yml -f compose.monitoring.yml stop prometheus node-exporter cadvisor
```

这是无需重建业务容器的暂停方式；应用内轻量计数与内部端口暂时保留，页面显示采集不可用。恢复使用相同配置的 `start prometheus node-exporter cadvisor`。开发环境在命令中同时保留 `compose.dev.yml`。

如需彻底关闭应用内采集，在正常发布窗口移除监控覆盖文件并重建应用配置：生产使用 `docker compose -f compose.yml up -d --no-deps api worker feishu`；开发使用 `docker compose -f compose.yml -f compose.dev.yml up -d --no-deps api worker feishu`。这一步会按需重建业务容器，不是无中断的动态开关；先等待当前工作完成。若手工在 `.env` 中设置过 `MONITORING_ENABLED=true`，需先移除或改为 `false`。监控历史保存在独立 `monitoring-data` 卷；停用不删除历史。不要使用 `down -v`，以免连同业务数据库卷一起删除。

## 官方资料

- [Linux 主机采集](https://prometheus.io/docs/guides/node-exporter/) 与 [Node Exporter 容器部署](https://github.com/prometheus/node_exporter)
- [cAdvisor 部署及宿主机权限](https://github.com/google/cadvisor/tree/v0.60.6) 与 [标签白名单](https://github.com/google/cadvisor/blob/v0.60.6/docs/runtime_options.md)
- [Docker 运行时指标](https://docs.docker.com/engine/containers/runmetrics/)
- [Prometheus 查询 API](https://prometheus.io/docs/prometheus/latest/querying/api/) 与 [存储保留策略](https://prometheus.io/docs/prometheus/latest/storage/)
- [Python 指标端点](https://prometheus.github.io/client_python/exporting/http/)
