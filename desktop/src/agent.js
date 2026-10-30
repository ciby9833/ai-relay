// 设备的执行循环：向 Relay 领活（长轮询），在授权文件夹里执行，回传结果。
// 设备只是执行者：不自己决定做什么，只做云端交来的、落在授权文件夹里的固定几种操作（列、读、写）。

const crypto = require("node:crypto");
const { list, read, write, FolderError } = require("./folders");
const { toText, Unsupported } = require("./parse");
const skills = require("./skills");

const TEXT_LIMIT = 60_000;

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
      folder = job.kind === "skill" ? null : this.options.folders.get(job.args.folder);
      if (job.kind === "list") {
        await this.report(job, true, await list(folder, job.args.path, job.args.query, job.args.limit || 200));
      } else if (job.kind === "read") {
        const file = await read(folder, job.args.path);
        const filename = job.args.path.split("/").pop();
        const version = { filename, size: file.size, modified: file.modified, sha256: crypto.createHash("sha256").update(file.data).digest("hex") };
        let parsed = null;
        try {
          parsed = await toText(filename, file.data);  // 在本机解析：只送文字，原文件不离开这台 Mac
        } catch (error) {
          if (!(error instanceof Unsupported)) throw error;
        }
        if (parsed) {
          await this.report(job, true, { ...version, text: parsed.text.slice(0, TEXT_LIMIT), truncated: parsed.text.length > TEXT_LIMIT,
            parsed_on: "device", kind: parsed.kind });
        } else {
          // 这台 Mac 解析不了的格式：上传给服务器解析（服务器不保存原文件）
          const response = await this.call(`/api/device/jobs/${job.id}/file`, {
            method: "POST", headers: { "Content-Type": "application/octet-stream", "X-Relay-Modified": file.modified }, body: file.data,
          });
          if (!response.ok) throw new Error(`上传失败：HTTP ${response.status}`);
        }
      } else if (job.kind === "write") {
        const response = await this.call(`/api/device/jobs/${job.id}/payload`);
        if (!response.ok) throw new Error(`取文件失败：HTTP ${response.status}`);
        const data = Buffer.from(await response.arrayBuffer());
        const saved = await write(folder, job.args.path, data, job.args.sha256);
        await this.report(job, true, { path: saved.path, verified: saved.verified });
      } else if (job.kind === "skill") {
        await this.report(job, true, await skills.run(this.options.folders, job.args.skill, job.args.input));
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
