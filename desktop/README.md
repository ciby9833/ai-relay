# Relay Mac 客户端

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

读文件时，文件会传到 Relay 服务器解析成文字（不保存原文件）。以后会改成在本机解析，只把需要的片段送出去。

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
2. 公证需要三个环境变量（App 专用密码在 appleid.apple.com 生成）：

   ```bash
   export APPLE_ID=you@example.com
   export APPLE_APP_SPECIFIC_PASSWORD=xxxx-xxxx-xxxx-xxxx
   export APPLE_TEAM_ID=XXXXXXXXXX
   ```

3. 自动更新的地址（一个能放静态文件的目录，例如服务器上的 `/desktop/`）：

   ```bash
   export RELAY_UPDATE_URL=https://translation.jtcargo.co.id/desktop/
   ```

4. 出包：`npm run dist`，产物在 `dist/`：Apple 芯片和 Intel 各一个 `.dmg`（给同事安装）和 `.zip`（自动更新用），以及 `latest-mac.yml`。
5. 发布新版本：改 `package.json` 里的 `version`，出包后把 `dist/` 里的 `.zip`、`.dmg`、`latest-mac.yml` 放到更新地址。已安装的客户端每 6 小时检查一次，下载后在下次重启时更新。

Windows 版以后用同一套代码出包（electron-builder 加 `--win` 和 Windows 代码签名证书）。
