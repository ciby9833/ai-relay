// Relay Mac 客户端：同一个 Relay（网页界面原样复用），加上桌面才有的：
// 菜单栏常驻、系统通知、本机文件夹授权（读写分开）、设备配对，以及自动更新。

const { app, BrowserWindow, Menu, Notification, Tray, dialog, ipcMain, nativeImage, safeStorage, shell } = require("electron");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { DeviceAgent } = require("./agent");
const { FolderStore } = require("./folders");

const DEFAULT_SERVER = "https://translation.jtcargo.co.id";
const SERVER = (process.env.RELAY_SERVER || DEFAULT_SERVER).replace(/\/$/, "");
const ORIGIN = new URL(SERVER).origin;
// 飞书登录要跳到飞书的授权页再回来：这些域名允许在窗口里打开，其他链接用系统浏览器打开
const LOGIN_HOSTS = [/\.feishu\.cn$/, /\.larksuite\.com$/, /\.feishu-boe\.cn$/];

let mainWindow = null;
let tray = null;
let quitting = false;
const store = new FolderStore(path.join(app.getPath("userData"), "folders.json"));
const secretsFile = path.join(app.getPath("userData"), "device.bin");

// ---------- 设备令牌：用系统钥匙串加密保存 ----------

function readDevice() {
  try {
    const raw = fs.readFileSync(secretsFile);
    return JSON.parse(safeStorage.isEncryptionAvailable() ? safeStorage.decryptString(raw) : raw.toString());
  } catch {
    return {};
  }
}

function writeDevice(value) {
  const text = JSON.stringify(value);
  fs.mkdirSync(path.dirname(secretsFile), { recursive: true });
  fs.writeFileSync(secretsFile, safeStorage.isEncryptionAvailable() ? safeStorage.encryptString(text) : text, { mode: 0o600 });
}

let device = {};
const agent = new DeviceAgent({
  server: SERVER,
  token: () => device.token || null,
  folders: store,
  version: app.getVersion(),
  onRevoked: () => {
    device = { revoked: true }; // 被撤销后不自动重新配对：要他在设置里点“重新连接”
    writeDevice(device);
    mainWindow?.webContents.send("relay:device-changed");
  },
  log: (message) => console.log(`[relay-device] ${message}`),
});

// ---------- 窗口 ----------

function allowedInWindow(url) {
  try {
    const target = new URL(url);
    return target.origin === ORIGIN || (target.protocol === "https:" && LOGIN_HOSTS.some((re) => re.test(target.hostname)));
  } catch {
    return false;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280, height: 860, minWidth: 900, minHeight: 600, title: "Relay", show: false,
    backgroundColor: "#faf9f5",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      additionalArguments: [`--relay-origin=${ORIGIN}`],
    },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  if (process.env.RELAY_SMOKE_SHOT) {
    // 自检：页面加载后截一张图并退出（打包前确认窗口、预加载脚本、页面都正常）
    mainWindow.webContents.once("did-finish-load", () => setTimeout(async () => {
      const bridge = await mainWindow.webContents.executeJavaScript("typeof window.relayDesktop");
      const image = await mainWindow.webContents.capturePage();
      fs.writeFileSync(process.env.RELAY_SMOKE_SHOT, image.toPNG());
      console.log(`[relay-smoke] url=${mainWindow.webContents.getURL()} bridge=${bridge}`);
      quitting = true;
      app.quit();
    }, 4000));
  }
  // 关窗口只是隐藏：继续在菜单栏里待命，提醒照常弹出
  mainWindow.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!allowedInWindow(url)) {
      event.preventDefault();
      if (/^https?:/.test(url)) void shell.openExternal(url);
    }
  });
  mainWindow.webContents.on("did-fail-load", (_event, code, description, url) => {
    if (code === -3) return; // 被中止（跳转）不算失败
    void mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(offlinePage(description, url))}`);
  });
  void mainWindow.loadURL(SERVER);
}

function offlinePage(reason, url) {
  return `<!doctype html><meta charset="utf-8"><title>Relay</title>
  <body style="font:15px -apple-system,sans-serif;background:#faf9f5;color:#141413;display:grid;place-items:center;height:100vh;margin:0">
  <div style="max-width:420px;text-align:center"><h2>连不上 Relay</h2><p style="color:#666">${reason}</p>
  <p><a href="${url || SERVER}" style="color:#c96442">重试</a></p></div></body>`;
}

function show() {
  if (!mainWindow) createWindow();
  else {
    mainWindow.show();
    mainWindow.focus();
  }
}

function buildTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "..", "build", "trayTemplate.png"));
  tray = new Tray(icon.isEmpty() ? nativeImage.createEmpty() : icon);
  if (icon.isEmpty()) tray.setTitle("Relay");
  tray.setToolTip("Relay");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "打开 Relay", click: show },
    { type: "separator" },
    { label: "退出 Relay", click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on("click", show);
}

// ---------- 网页能用的桌面能力（只给 Relay 自己的页面） ----------

function trusted(event) {
  try {
    return new URL(event.senderFrame.url).origin === ORIGIN;
  } catch {
    return false;
  }
}

function handle(channel, fn) {
  ipcMain.handle(channel, async (event, ...args) => {
    if (!trusted(event)) throw new Error("不允许");
    return fn(...args);
  });
}

function registerBridge() {
  handle("relay:status", () => ({
    paired: Boolean(device.token), revoked: Boolean(device.revoked), deviceId: device.id || null,
    name: os.hostname().replace(/\.local$/, ""), platform: process.platform, version: app.getVersion(),
  }));
  handle("relay:paired", async (info) => {
    device = { token: String(info.token), id: String(info.id) };
    writeDevice(device);
    agent.start();
    return true;
  });
  handle("relay:unpair", async () => {
    agent.stop();
    device = {};
    writeDevice(device);
    return true;
  });
  handle("relay:notify", ({ title, body }) => {
    if (!Notification.isSupported()) return false;
    const note = new Notification({ title: String(title || "Relay").slice(0, 80), body: String(body || "").slice(0, 300) });
    note.on("click", show);
    note.show();
    return true;
  });
  handle("relay:folders", () => store.local());
  handle("relay:folders-add", async () => {
    const picked = await dialog.showOpenDialog(mainWindow, {
      title: "授权一个文件夹给 Relay", buttonLabel: "授权", properties: ["openDirectory", "createDirectory"],
    });
    if (picked.canceled || !picked.filePaths[0]) return store.local();
    await store.add(picked.filePaths[0]);
    await agent.reportFolders();
    return store.local();
  });
  handle("relay:folders-update", async (id, change) => {
    await store.update(id, change || {});
    await agent.reportFolders();
    return store.local();
  });
  handle("relay:folders-remove", async (id) => {
    await store.remove(id);
    await agent.reportFolders();
    return store.local();
  });
  handle("relay:reveal", (id) => shell.openPath(store.get(id).root));
}

// ---------- 自动更新（打包版、配置了更新地址时） ----------

function checkForUpdates() {
  // 只有正式打包（带更新地址，打包时生成 app-update.yml）的版本才检查更新；本地调试、目录版跳过
  if (!app.isPackaged || !fs.existsSync(path.join(process.resourcesPath, "app-update.yml"))) return;
  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.autoDownload = true;
    autoUpdater.on("error", (error) => console.log(`[relay-update] ${error.message}`));
    const check = () => autoUpdater.checkForUpdatesAndNotify().catch((error) => console.log(`[relay-update] ${error.message}`));
    void check();
    setInterval(check, 6 * 60 * 60 * 1000);
  } catch (error) {
    console.log(`[relay-update] 未启用：${error.message}`);
  }
}

// ---------- 启动 ----------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", show);
  app.whenReady().then(async () => {
    app.setAppUserModelId("com.relay.desktop");
    await store.load();
    device = readDevice();
    registerBridge();
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { role: "appMenu" }, { role: "editMenu" }, { role: "viewMenu" }, { role: "windowMenu" },
    ]));
    createWindow();
    buildTray();
    agent.start();
    checkForUpdates();
  });
  app.on("activate", show);
  app.on("before-quit", () => { quitting = true; agent.stop(); });
}
