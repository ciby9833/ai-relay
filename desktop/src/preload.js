// 只给 Relay 自己的页面开放几项桌面能力（系统通知、授权文件夹、设备配对）；别的网页拿不到。
const { contextBridge, ipcRenderer } = require("electron");

const origin = (process.argv.find((arg) => arg.startsWith("--relay-origin=")) || "").split("=")[1];

if (origin && window.location.origin === origin) {
  contextBridge.exposeInMainWorld("relayDesktop", {
    status: () => ipcRenderer.invoke("relay:status"),
    paired: (info) => ipcRenderer.invoke("relay:paired", info),
    unpair: () => ipcRenderer.invoke("relay:unpair"),
    notify: (title, body) => ipcRenderer.invoke("relay:notify", { title, body }),
    folders: () => ipcRenderer.invoke("relay:folders"),
    addFolder: () => ipcRenderer.invoke("relay:folders-add"),
    updateFolder: (id, change) => ipcRenderer.invoke("relay:folders-update", id, change),
    removeFolder: (id) => ipcRenderer.invoke("relay:folders-remove", id),
    reveal: (id) => ipcRenderer.invoke("relay:reveal", id),
    onDeviceChanged: (callback) => {
      const listener = () => callback();
      ipcRenderer.on("relay:device-changed", listener);
      return () => ipcRenderer.removeListener("relay:device-changed", listener);
    },
  });
}
