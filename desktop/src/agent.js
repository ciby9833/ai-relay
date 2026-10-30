// 设备的执行循环：向 Relay 领活（长轮询），在授权文件夹里执行，回传结果。
// 设备只是执行者：不自己决定做什么，只做云端交来的、落在授权文件夹里的固定几种操作（列、读、写）。

const { list, read, write, FolderError } = require("./folders");

const RETRY_MS = [2000, 5000, 15000, 30000];

class DeviceAgent {
  /**
   * @param {{ server: string, token: () => string | null, folders: import("./folders").FolderStore,
   *           version: string, onRevoked: () => void, log?: (msg: string) => void, fetchImpl?: typeof fetch }} options
   */
  constructor(options) {
    this.options = options;
    this.running = false;
    this.failures = 0;
    this.fetch = options.fetchImpl || fetch;
    this.log = options.log || (() => undefined);
  }

  headers(extra = {}) {
    return { Authorization: `Device ${this.options.token()}`, ...extra };
  }

  async call(path, init = {}) {
    const response = await this.fetch(`${this.options.server}${path}`, { ...init, headers: this.headers(init.headers) });
    if (response.status === 401) {
      this.stop();
      this.options.onRevoked(); // 网页上撤销了这台设备：停下，等他重新连接
      throw new Error("revoked");
    }
    return response;
  }

  /** 把授权文件夹（只有名字和读写开关）告诉 Relay。 */
  async reportFolders() {
    if (!this.options.token()) return;
    await this.call("/api/device/folders", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folders: this.options.folders.public(), app_version: this.options.version }),
    }).catch((error) => this.log(`上报文件夹失败：${error.message}`));
  }

  start() {
    if (this.running || !this.options.token()) return;
    this.running = true;
    void this.reportFolders();
    void this.loop();
  }

  stop() {
    this.running = false;
  }

  async loop() {
    while (this.running) {
      try {
        const response = await this.call("/api/device/jobs?wait=25");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const jobs = await response.json();
        this.failures = 0;
        for (const job of jobs) await this.run(job);
      } catch (error) {
        if (!this.running) return;
        const wait = RETRY_MS[Math.min(this.failures, RETRY_MS.length - 1)];
        this.failures += 1;
        this.log(`领活失败（${error.message}），${wait / 1000} 秒后重试`);
        await new Promise((resolve) => setTimeout(resolve, wait));
      }
    }
  }

  async report(job, ok, data, error) {
    await this.call(`/api/device/jobs/${job.id}/result`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ok ? { ok: true, data } : { ok: false, error: String(error).slice(0, 900) }),
    });
  }

  async run(job) {
    let folder;
    try {
      folder = this.options.folders.get(job.args.folder);
      if (job.kind === "list") {
        await this.report(job, true, await list(folder, job.args.path, job.args.query, job.args.limit || 200));
      } else if (job.kind === "read") {
        const file = await read(folder, job.args.path);
        const response = await this.call(`/api/device/jobs/${job.id}/file`, {
          method: "POST", headers: { "Content-Type": "application/octet-stream", "X-Relay-Modified": file.modified }, body: file.data,
        });
        if (!response.ok) throw new Error(`上传失败：HTTP ${response.status}`);
      } else if (job.kind === "write") {
        const response = await this.call(`/api/device/jobs/${job.id}/payload`);
        if (!response.ok) throw new Error(`取文件失败：HTTP ${response.status}`);
        const data = Buffer.from(await response.arrayBuffer());
        const saved = await write(folder, job.args.path, data, job.args.sha256);
        await this.report(job, true, { path: saved.path, verified: saved.verified });
      } else {
        throw new FolderError(`不支持的操作：${job.kind}`);
      }
    } catch (error) {
      if (error.message === "revoked") return;
      // 自己判断得出的失败（不在授权范围、文件不存在……）原样告诉助理；其他错误也回传，不让云端干等
      await this.report(job, false, null, error.message).catch(() => undefined);
    }
  }
}

module.exports = { DeviceAgent };
