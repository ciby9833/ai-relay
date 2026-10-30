// 本机解析和本机技能：格式和服务器一致；技能结果写成新文件并核对；读文件时只回传文字（原文件不离开 Mac）。
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const ExcelJS = require("exceljs");
const { FolderStore } = require("../src/folders");
const { toText, Unsupported } = require("../src/parse");
const skills = require("../src/skills");
const { DeviceAgent } = require("../src/agent");

async function workbook(rows, sheet = "明细") {
  const book = new ExcelJS.Workbook();
  const ws = book.addWorksheet(sheet);
  rows.forEach((r) => ws.addRow(r));
  return Buffer.from(await book.xlsx.writeBuffer());
}

async function setup() {
  const base = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "relay-skills-")));
  const data = path.join(base, "数据");
  const out = path.join(base, "成果");
  await fs.mkdir(data);
  await fs.mkdir(out);
  await fs.writeFile(path.join(data, "9月.xlsx"), await workbook([["单号", "网点", "重量"], ["JT001", "Medan", 12], ["JT002", "Medan", 8], ["JT003", "Jakarta", 5]]));
  await fs.writeFile(path.join(data, "10月.xlsx"), await workbook([["单号", "网点", "重量"], ["JT001", "Medan", 12], ["JT002", "Medan", 9.5], ["JT004", "Bali", 3]]));
  await fs.writeFile(path.join(data, "费用.csv"), "网点,费用\nMedan,\"1,200\"\nJakarta,300\nMedan,800\n");
  await fs.writeFile(path.join(data, "旧.doc"), "binary");
  const store = new FolderStore(path.join(base, "folders.json"));
  await store.load();
  const src = await store.add(data);
  const dst = await store.add(out);
  await store.update(dst.id, { write: true });
  return { base, out, store, src, dst };
}

test("files are parsed on the Mac in the same format as the server", async () => {
  const { base } = await setup();
  const sheet = await toText("9月.xlsx", await fs.readFile(path.join(base, "数据", "9月.xlsx")));
  assert.equal(sheet.kind, "xlsx");
  assert.match(sheet.text, /^## 工作表「明细」，共 4 行 3 列/);
  assert.match(sheet.text, /R2 \| A: JT001 \| B: Medan \| C: 12/);
  const table = await toText("费用.csv", await fs.readFile(path.join(base, "数据", "费用.csv")));
  assert.match(table.text, /R2 \| A: Medan \| B: 1,200/);  // 引号里的逗号不拆开
  await assert.rejects(toText("旧.doc", Buffer.from("x")), Unsupported);
});

test("compare two tables: added, removed and changed cells go to a new, verified file", async () => {
  const { out, store, src, dst } = await setup();
  const result = await skills.run(store, "compare_tables", {
    left: { folder: src.id, path: "9月.xlsx" }, right: { folder: src.id, path: "10月.xlsx" }, key: "单号",
    output: { folder: dst.id, path: "9月对比10月.xlsx" } });
  assert.deepEqual(result.counts, { left_rows: 3, right_rows: 3, added: 1, removed: 1, changed_cells: 1, changed_rows: 1, duplicate_keys: 0 });
  assert.deepEqual(result.examples.changed, [{ key: "JT002", column: "重量", before: "8", after: "9.5" }]);
  assert.deepEqual(result.examples.added, ["JT004"]);
  assert.equal(result.output.path, "9月对比10月.xlsx");
  assert.ok(result.output.verified);
  // 再跑一次：不覆盖，换个名字
  const again = await skills.run(store, "compare_tables", {
    left: { folder: src.id, path: "9月.xlsx" }, right: { folder: src.id, path: "10月.xlsx" }, key: "单号",
    output: { folder: dst.id, path: "9月对比10月.xlsx" } });
  assert.equal(again.output.path, "9月对比10月 (1).xlsx");
  assert.deepEqual((await fs.readdir(out)).sort(), ["9月对比10月 (1).xlsx", "9月对比10月.xlsx"]);
  // 写到只读的文件夹、用不存在的列：拒绝
  await assert.rejects(skills.run(store, "compare_tables", { left: { folder: src.id, path: "9月.xlsx" }, right: { folder: src.id, path: "10月.xlsx" },
    key: "单号", output: { folder: src.id, path: "x.xlsx" } }), /没有授权写入/);
  await assert.rejects(skills.run(store, "compare_tables", { left: { folder: src.id, path: "9月.xlsx" }, right: { folder: src.id, path: "10月.xlsx" },
    key: "运单", output: { folder: dst.id, path: "x.xlsx" } }), /没有“运单”这一列/);
  await assert.rejects(skills.run(store, "delete_everything", {}), /不认识技能/);
});

test("summarise a table: group, count and sum into a new verified file", async () => {
  const { store, src, dst } = await setup();
  const result = await skills.run(store, "summarize_table", {
    source: { folder: src.id, path: "费用.csv" }, group_by: ["网点"], sum: ["费用"], output: { folder: dst.id, path: "费用汇总" } });
  assert.deepEqual(result.top, [["Medan", 2, 2000], ["Jakarta", 1, 300]]);
  assert.deepEqual(result.totals, ["合计", 3, 2300]);
  assert.equal(result.output.path, "费用汇总.xlsx");
  assert.ok(result.output.verified);
});

test("reading a file sends text only; formats the Mac can't parse fall back to the server", async () => {
  const { store, src } = await setup();
  const calls = [];
  const jobs = [[{ id: "r1", kind: "read", args: { folder: src.id, path: "9月.xlsx" } }, { id: "r2", kind: "read", args: { folder: src.id, path: "旧.doc" } }]];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, body: init.body });
    if (url.includes("/api/device/jobs?wait")) return jobs.length ? Response.json(jobs.shift()) : new Response(null, { status: 401 });
    return Response.json({ ok: true });
  };
  const agent = new DeviceAgent({ server: "https://relay.test", token: () => "t", folders: store, version: "0.2.0", onRevoked: () => {}, fetchImpl });
  agent.start();
  await new Promise((r) => setTimeout(r, 500));
  const local = JSON.parse(calls.find((c) => c.url.endsWith("/jobs/r1/result")).body);
  assert.equal(local.data.parsed_on, "device");
  assert.match(local.data.text, /R3 \| A: JT002/);
  assert.equal(local.data.sha256.length, 64);
  assert.ok(!calls.some((c) => c.url.endsWith("/jobs/r1/file")), "能本机解析的不上传原文件");
  assert.ok(calls.some((c) => c.url.endsWith("/jobs/r2/file")), "本机解析不了的才上传给服务器");
});

function tinyPdf(lines) {
  // 一个最小的、合法的 PDF：一页，用 Helvetica 写几行字（测试本机 PDF 解析）
  const stream = `BT /F1 12 Tf 72 720 Td ${lines.map((l, i) => `${i ? "0 -16 Td " : ""}(${l}) Tj`).join(" ")} ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets = [];
  objects.forEach((obj, i) => { offsets.push(body.length); body += `${i + 1} 0 obj\n${obj}\nendobj\n`; });
  const xref = body.length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, "latin1");
}

test("PDFs are parsed page by page on the Mac", async () => {
  const result = await toText("invoice.pdf", tinyPdf(["Invoice JT001 total 4500", "Due 2026-11-05 Medan station"]));
  assert.equal(result.kind, "pdf");
  assert.match(result.text, /^## 第 1 页\n/);
  assert.match(result.text, /Invoice JT001 total 4500/);
});
