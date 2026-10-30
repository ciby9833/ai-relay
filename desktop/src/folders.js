// 授权文件夹：用户在客户端里选的文件夹，读、写分开授权。
// 所有本机文件操作都只能落在这些文件夹里：按真实路径检查，软链接也不能把路径带出去。
// 云端只知道文件夹的 id 和名字，完整路径只留在这台 Mac 上。

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const MAX_READ = 20 * 1024 * 1024;
const SEARCH_DEPTH = 6;

class FolderError extends Error {}

class FolderStore {
  /** @param {string} file 保存授权列表的 JSON 文件（在 app 的 userData 里） */
  constructor(file) {
    this.file = file;
    this.folders = [];
  }

  async load() {
    try {
      this.folders = JSON.parse(await fs.readFile(this.file, "utf8"));
    } catch {
      this.folders = [];
    }
    return this.folders;
  }

  async save() {
    await fs.mkdir(path.dirname(this.file), { recursive: true });
    await fs.writeFile(this.file, JSON.stringify(this.folders, null, 2), { mode: 0o600 });
  }

  /** 给云端看的：只有 id、名字、读写开关 */
  public() {
    return this.folders.map(({ id, label, read, write }) => ({ id, label, read, write }));
  }

  /** 给本机设置页看的：加上完整路径 */
  local() {
    return this.folders.map(({ id, label, read, write, root }) => ({ id, label, read, write, root }));
  }

  async add(root) {
    const real = await fs.realpath(root);
    const stat = await fs.stat(real);
    if (!stat.isDirectory()) throw new FolderError("只能授权文件夹");
    if (real === path.parse(real).root || real === require("node:os").homedir()) {
      throw new FolderError("不能授权整个磁盘或整个用户目录，请选具体的工作文件夹");
    }
    const existing = this.folders.find((f) => f.root === real);
    if (existing) return existing;
    let label = path.basename(real);
    for (let n = 2; this.folders.some((f) => f.label === label); n += 1) label = `${path.basename(real)} ${n}`;
    const folder = { id: crypto.randomUUID(), label, root: real, read: true, write: false };
    this.folders.push(folder);
    await this.save();
    return folder;
  }

  async update(id, change) {
    const folder = this.get(id);
    if (typeof change.read === "boolean") folder.read = change.read;
    if (typeof change.write === "boolean") folder.write = change.write;
    await this.save();
    return folder;
  }

  async remove(id) {
    this.folders = this.folders.filter((f) => f.id !== id);
    await this.save();
  }

  get(id) {
    const folder = this.folders.find((f) => f.id === id);
    if (!folder) throw new FolderError("这个文件夹已经不在授权列表里了");
    return folder;
  }
}

function inside(root, target) {
  const relative = path.relative(root, target);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

/** 相对路径 → 授权文件夹里的真实路径。不存在的文件按它所在文件夹的真实路径检查。 */
async function resolve(folder, relative, { mustExist = true } = {}) {
  const clean = String(relative || "").replace(/\\/g, "/");
  if (clean.startsWith("/") || clean.startsWith("~") || /^[a-zA-Z]:/.test(clean) || clean.split("/").includes("..")) {
    throw new FolderError("路径只能是授权文件夹里的相对路径");
  }
  const root = await fs.realpath(folder.root).catch(() => {
    throw new FolderError(`授权的文件夹「${folder.label}」已经不存在了`);
  });
  const target = path.resolve(root, clean);
  if (!inside(root, target)) throw new FolderError("路径越出了授权文件夹");
  let real;
  try {
    real = await fs.realpath(target);
  } catch {
    if (mustExist) throw new FolderError(`找不到文件：${clean}`);
    const parent = await fs.realpath(path.dirname(target)).catch(() => null);
    if (parent && !inside(root, parent)) throw new FolderError("路径越出了授权文件夹");
    return { root, real: target };
  }
  if (!inside(root, real)) throw new FolderError("这个路径通过链接指向了授权文件夹以外的地方，不能使用");
  return { root, real };
}

function rel(root, full) {
  return path.relative(root, full).split(path.sep).join("/");
}

/** 列文件：不带关键字时列这一层；带关键字时往下找文件名包含它的（隐藏文件不列）。 */
async function list(folder, relative, query, limit = 200) {
  if (!folder.read) throw new FolderError(`文件夹「${folder.label}」没有授权读取`);
  const { root, real } = await resolve(folder, relative || "");
  const entries = [];
  const needle = String(query || "").toLowerCase();
  let truncated = false;

  async function walk(dir, depth) {
    let items;
    try {
      items = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    items.sort((a, b) => a.name.localeCompare(b.name));
    for (const item of items) {
      if (item.name.startsWith(".")) continue;
      if (entries.length >= limit) {
        truncated = true;
        return;
      }
      const full = path.join(dir, item.name);
      if (item.isSymbolicLink()) {
        const target = await fs.realpath(full).catch(() => null);
        if (!target || !inside(root, target)) continue; // 指向外面的链接：不列
      }
      const isDir = item.isDirectory();
      if (!needle || item.name.toLowerCase().includes(needle)) {
        if (isDir) entries.push({ path: rel(root, full), dir: true });
        else {
          const stat = await fs.stat(full).catch(() => null);
          if (stat) entries.push({ path: rel(root, full), size: stat.size, modified: stat.mtime.toISOString() });
        }
      }
      if (needle && isDir && depth < SEARCH_DEPTH) await walk(full, depth + 1);
    }
  }

  await walk(real, 0);
  return { entries, truncated };
}

/** 读文件：返回内容和版本（大小、修改时间）。 */
async function read(folder, relative) {
  if (!folder.read) throw new FolderError(`文件夹「${folder.label}」没有授权读取`);
  const { real } = await resolve(folder, relative);
  const stat = await fs.stat(real);
  if (!stat.isFile()) throw new FolderError("这是文件夹，不是文件");
  if (stat.size > MAX_READ) throw new FolderError(`文件太大（${Math.round(stat.size / 1024 / 1024)}MB），超过 20MB 的上限`);
  return { data: await fs.readFile(real), modified: stat.mtime.toISOString(), size: stat.size };
}

/** 写文件：只新建。同名时换成“名字 (1).扩展名”，不覆盖；写完读回核对哈希。 */
async function write(folder, relative, data, sha256) {
  if (!folder.write) throw new FolderError(`文件夹「${folder.label}」没有授权写入`);
  if (sha256 && crypto.createHash("sha256").update(data).digest("hex") !== sha256) {
    throw new FolderError("下载的内容和 Relay 里的文件不一致，没有写入");
  }
  const { root, real } = await resolve(folder, relative, { mustExist: false });
  // 要新建子文件夹时，先确认最近一个已存在的上级（按真实路径）在授权文件夹里，再建：防止经由软链接建到外面
  let ancestor = path.dirname(real);
  while (!(await fs.stat(ancestor).then(() => true, () => false))) ancestor = path.dirname(ancestor);
  if (!inside(root, await fs.realpath(ancestor))) throw new FolderError("路径越出了授权文件夹");
  await fs.mkdir(path.dirname(real), { recursive: true });
  const dirReal = await fs.realpath(path.dirname(real));
  if (!inside(root, dirReal)) throw new FolderError("路径越出了授权文件夹");
  const ext = path.extname(real);
  const base = path.basename(real, ext);
  for (let n = 0; n < 100; n += 1) {
    const candidate = path.join(dirReal, n === 0 ? `${base}${ext}` : `${base} (${n})${ext}`);
    try {
      await fs.writeFile(candidate, data, { flag: "wx" }); // wx：文件已存在就失败，绝不覆盖
    } catch (error) {
      if (error.code === "EEXIST") continue;
      throw error;
    }
    const back = await fs.readFile(candidate);
    const verified = crypto.createHash("sha256").update(back).digest("hex") === crypto.createHash("sha256").update(data).digest("hex");
    return { path: rel(root, candidate), verified, full: candidate };
  }
  throw new FolderError("同名文件太多，没有写入");
}

/** 替换已有文件（只在他明确选择“覆盖原文件”时用）：写之前再核对一次版本没变；先写临时文件再换上去，写完读回核对。 */
async function replace(folder, relative, data, expectedSha256) {
  if (!folder.write) throw new FolderError(`文件夹「${folder.label}」没有授权写入`);
  const { root, real } = await resolve(folder, relative);
  const current = await fs.readFile(real);
  if (crypto.createHash("sha256").update(current).digest("hex") !== expectedSha256) {
    throw new FolderError("这个文件在预览之后被改过了，没有覆盖；请重新预览");
  }
  const temp = path.join(path.dirname(real), `.relay-tmp-${crypto.randomUUID()}`);
  await fs.writeFile(temp, data, { flag: "wx" });
  try {
    await fs.rename(temp, real);  // 同一个文件夹里换名：要么是旧文件，要么是新文件，不会只写一半
  } catch (error) {
    await fs.rm(temp, { force: true });
    throw error;
  }
  const back = await fs.readFile(real);
  const verified = crypto.createHash("sha256").update(back).digest("hex") === crypto.createHash("sha256").update(data).digest("hex");
  return { path: rel(root, real), verified, full: real };
}

module.exports = { FolderStore, FolderError, resolve, list, read, write, replace, MAX_READ };
