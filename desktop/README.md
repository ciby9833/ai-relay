# Relay Mac 客户端

## 下载与更新入口

- 面向用户的下载页：Web 服务发布后访问 `https://translation.jtcargo.co.id/download/`（无需登录）。本地预览运行 `frontend/` 的 `npm run dev`，打开 `/download/`。页面从 `/desktop/latest-mac.yml` 读取已发布版本、两个架构的 DMG 链接及文件大小，不在网页中写死版本号。
- 安装包和自动更新源：`https://translation.jtcargo.co.id/desktop/`。这个目录继续服务 `.dmg`、`.zip`、`.blockmap` 和 `latest-mac.yml`，不改成网页路由。
- 0.1.0 提供 Apple 芯片和 Intel 两个版本，最低 macOS 13。下载 DMG 后将 Relay 拖入 Applications。
- 打包客户端在启动时检查更新，并在运行期间每 6 小时检查一次、自动下载。完全退出 Relay 后重新打开以使用新版；关闭窗口只是隐藏，仍驻留菜单栏。

## 客户端能力

同一个 Relay（界面直接用网页版），加上桌面才有的能力：

- **菜单栏常驻**：关窗口只是隐藏，Relay 主动提醒时弹 **macOS 系统通知**（点通知回到窗口）。
- **本机文件夹授权**：在“提醒设置 → 这台 Mac”里选文件夹，**读、写分开授权**。助理可以列文件、读文件（xlsx、docx、pdf、csv、txt…）、把它生成的文件存进来（**只新建、同名自动换名、不覆盖**，存完读回核对）。
- **设备配对**：登录后自动把这台 Mac 配对到你的账号；网页上“账号与工作区 → 登录过的电脑”可以随时撤销，撤销后立刻失效。退出登录时也会断开。

## 边界（为什么安全）

- 只有 Relay 自己的页面能用这些桌面能力（预加载脚本按来源判断；主进程每次调用再查一次）。
- 所有本机操作都只落在授权文件夹里：按真实路径检查，`..`、绝对路径、指向外面的软链接都会被拒绝；不能授权整个磁盘或整个用户目录。
- 云端只知道文件夹的**名字和相对路径**，完整路径只留在这台 Mac 上。
- 设备只是执行者：只做云端交来的三种固定操作（列、读、写），不执行任意脚本或命令。
- 设备令牌用系统钥匙串加密保存。

- **本机解析**（0.2.0 起）：xlsx、csv、pdf、docx、txt 在这台 Mac 上解析成文字（格式和服务器一致，带单元格 / 页码定位），只把文字送给助理，原文件不离开电脑；本机解析不了的格式（例如 .doc、.pptx、扫描件）才上传给服务器解析（服务器不保存原文件）。
- **项目说明**：授权文件夹的根目录里可以放一份 `RELAY.md`（你自己写：这个项目是什么、数据在哪些文件、产出放哪），助理处理这个文件夹前会先读。
- **修改已有 Excel**（0.3.0 起）：助理先读出要改的格子现在的值，做成卡片给你确认（原值 → 新值）；默认另存为新文件，只有你明确选“覆盖原文件”才覆盖，覆盖前在同一个文件夹里备份原文件。写之前核对文件没被改过，写之后核对其他格子没变；文件里有图表、透视表、图片、宏时只能另存。
- **按模板生成**（0.3.0 起）：在 Word / Excel 模板里写 `{{本周完成}}` 这样的占位符，助理整理好内容后生成一个新文件（模板不改），核对没有留下占位符。
- **本机技能**（0.2.0 起）：对比两张表、汇总一张表。技能的定义在服务端（`backend/app/skills.py`），实现在 `src/skills.js`；客户端只执行认识的技能。原文件只读，结果写成新文件并重新打开核对；回传给云端的只有数字和少量示例。

## 开发

```bash
npm install
npm start                      # 连生产环境
RELAY_SERVER=http://localhost:8098 npm start   # 连本地后端
npm test                       # 授权文件夹边界、执行循环的测试
```

自检（打包前确认窗口、预加载脚本、页面都正常）：

```bash
RELAY_SMOKE_SHOT=/tmp/relay.png npx electron .
```

## 打包、签名、公证、发布

1. 本机钥匙串里安装 **Developer ID Application** 证书（Apple 开发者账号里生成）。electron-builder 会自动找到它签名。
2. 公证凭据（只做一次）：在终端运行下面的命令，按提示输入 App 专用密码（appleid.apple.com → 登录与安全 → App 专用密码），
   它会存进钥匙串，名字叫 `relay`；之后打包时用 `APPLE_KEYCHAIN_PROFILE=relay` 引用，密码不出现在命令和环境变量里：

   ```bash
   xcrun notarytool store-credentials relay --apple-id 你的AppleID邮箱 --team-id VWQT77VXY4
   export APPLE_KEYCHAIN_PROFILE=relay
   ```

   （也可以改用 APPLE_ID、APPLE_APP_SPECIFIC_PASSWORD、APPLE_TEAM_ID 三个环境变量。）

3. 自动更新的地址（一个能放静态文件的目录，例如服务器上的 `/desktop/`）：

   ```bash
   export RELAY_UPDATE_URL=https://translation.jtcargo.co.id/desktop/
   ```

4. 出包：`npm run dist`，产物在 `dist/`：Apple 芯片和 Intel 各一个 `.dmg`（给同事安装）和 `.zip`（自动更新用），以及 `latest-mac.yml`。
5. 发布新版本：改 `package.json` 里的 `version`，出包后把 `dist/` 里的 `.zip`、`.dmg`、`.blockmap`、`latest-mac.yml` 放到服务器的 `/var/www/relay/desktop-releases/`（就是 `https://translation.jtcargo.co.id/desktop/`）。先放安装包，最后放 `latest-mac.yml`。已安装的客户端每 6 小时检查一次，下载后在下次重启时更新。

发布时的完整性要求：

- 在 `desktop/` 中设置上面的 `RELAY_UPDATE_URL`，运行 `APPLE_KEYCHAIN_PROFILE=relay npm run dist`。须等两个架构及 DMG、ZIP 全部构建完成；某一个架构公证通过不代表整次发布完成。
- 验证两个 `.app` 的签名、公证票据和 Gatekeeper 接受状态，并实际启动检查。
- 先上传两个架构的 DMG、ZIP 和 blockmap，校验远端大小与校验和。已有版本的文件保持不变。
- 最后将新清单上传为临时文件，再在服务器同目录原子重命名为 `latest-mac.yml`，避免用户读到半份清单。下载页面与自动更新使用同一份清单，同时切换到新版本。
- 从外网检查下载页、两个 DMG 及清单中的 ZIP 链接。更新清单响应保持 `Cache-Control: no-cache`。

网页内容和前端 UI 的更新只需发布 Web 服务；Electron 主进程、预加载桥接、本机文件执行逻辑及打包依赖的更新，需要提升客户端版本、重新签名公证并发布安装包。

Windows 版以后用同一套代码出包（electron-builder 加 `--win` 和 Windows 代码签名证书）。
