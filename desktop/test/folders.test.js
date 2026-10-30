// 授权文件夹的边界：只能读写授权的文件夹，软链接不能带出去，写入只新建不覆盖，读写分开授权。
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { FolderStore, list, read, write } = require("../src/folders");
const { DeviceAgent } = require("../src/agent");

async function setup() {
  const base = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "relay-folders-")));
  const work = path.join(base, "报价");
  const outside = path.join(base, "私人");
  await fs.mkdir(path.join(work, "9月"), { recursive: true });
  await fs.mkdir(outside);
  await fs.writeFile(path.join(work, "9月", "报价单.csv"), "单号,重量\nJT001,12\n");
  await fs.writeFile(path.join(work, ".DS_Store"), "x");
  await fs.writeFile(path.join(outside, "工资.txt"), "secret");
  await fs.symlink(outside, path.join(work, "捷径"));
  await fs.symlink(path.join(outside, "工资.txt"), path.join(work, "工资链接.txt"));
  const store = new FolderStore(path.join(base, "folders.json"));
  await store.load();
  const folder = await store.add(work);
  return { base, work, outside, store, folder };
}

test("only files inside the authorised folder can be listed and read", async () => {
  const { folder } = await setup();
  const top = await list(folder, "", "");
  assert.deepEqual(top.entries.map((e) => e.path), ["9月"]); // 隐藏文件、指向外面的链接都不列
  const found = await list(folder, "", "报价");
  assert.deepEqual(found.entries.map((e) => e.path), ["9月/报价单.csv"]);
  const file = await read(folder, "9月/报价单.csv");
  assert.match(file.data.toString(), /JT001/);
  for (const bad of ["../私人/工资.txt", "/etc/passwd", "捷径/工资.txt", "工资链接.txt", "~/x"]) {
    await assert.rejects(read(folder, bad), /相对路径|越出|链接|找不到/, bad);
  }
});

test("writing needs write permission, never overwrites, and is verified", async () => {
  const { work, store, folder } = await setup();
  await assert.rejects(write(folder, "周报.xlsx", Buffer.from("A")), /没有授权写入/);
  await store.update(folder.id, { write: true });
  const data = Buffer.from("report-v1");
  const sha = crypto.createHash("sha256").update(data).digest("hex");
  const first = await write(folder, "成果/周报.xlsx", data, sha);
  const second = await write(folder, "成果/周报.xlsx", Buffer.from("report-v2"));
  assert.equal(first.path, "成果/周报.xlsx");
  assert.equal(second.path, "成果/周报 (1).xlsx");
  assert.ok(first.verified && second.verified);
  assert.equal((await fs.readFile(path.join(work, "成果", "周报.xlsx"))).toString(), "report-v1"); // 原来的没被覆盖
  await assert.rejects(write(folder, "x.txt", data, "0".repeat(64)), /不一致/);
  await assert.rejects(write(folder, "捷径/新建/a.txt", data), /越出/); // 经由软链接建到外面：不行
  await assert.rejects(write(folder, "../私人/a.txt", data), /相对路径/);
});

test("the whole disk or home folder cannot be authorised; the cloud only sees names", async () => {
  const { store } = await setup();
  await assert.rejects(store.add(os.homedir()), /不能授权/);
  assert.deepEqual(Object.keys(store.public()[0]).sort(), ["id", "label", "read", "write"]);
});

test("the device agent runs a job from the cloud and reports back; a revoked device stops", async () => {
  const { folder, store } = await setup();
  const calls = [];
  let served = false;
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body });
    if (url.endsWith("/api/device/jobs?wait=25")) {
      if (served) return new Response(null, { status: 401 });
      served = true;
      return Response.json([{ id: "j1", kind: "list", args: { folder: folder.id, path: "", query: "报价" } }]);
    }
    return Response.json({ ok: true });
  };
  let revoked = false;
  const agent = new DeviceAgent({ server: "https://relay.test", token: () => "t", folders: store, version: "0.1.0",
    onRevoked: () => { revoked = true; }, fetchImpl });
  agent.start();
  await new Promise((resolve) => setTimeout(resolve, 200));
  const result = calls.find((c) => c.url.endsWith("/api/device/jobs/j1/result"));
  assert.deepEqual(JSON.parse(result.body).data.entries.map((e) => e.path), ["9月/报价单.csv"]);
  const reported = calls.find((c) => c.url.endsWith("/api/device/folders"));
  assert.ok(!reported.body.includes("/"), "上报的文件夹信息里不能有完整路径");
  assert.ok(revoked && !agent.running);
});
