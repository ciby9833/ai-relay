// 修改已有 Excel 和按模板生成：先预览、默认另存、覆盖先备份、版本变了不写、有图表不让覆盖、其他格子不变；模板填完核对。
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const ExcelJS = require("exceljs");
const PizZip = require("pizzip");
const { FolderStore } = require("../src/folders");
const skills = require("../src/skills");
const { toText } = require("../src/parse");

async function setup() {
  const base = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), "relay-edit-")));
  const book = new ExcelJS.Workbook();
  const ws = book.addWorksheet("反馈");
  ws.addRows([["网点", "问题", "处理结果"], ["Medan", "延误", ""], ["Jakarta", "破损", "已赔付"]]);
  ws.getCell("E1").value = { formula: "1+1", result: 2 };
  await fs.writeFile(path.join(base, "反馈表.xlsx"), Buffer.from(await book.xlsx.writeBuffer()));
  const store = new FolderStore(path.join(base, "folders.json"));
  await store.load();
  const folder = await store.add(base);
  await store.update(folder.id, { write: true });
  return { base, store, folder };
}

const sha = (data) => crypto.createHash("sha256").update(data).digest("hex");

test("edits are previewed, saved as a new file by default, and nothing else changes", async () => {
  const { base, store, folder } = await setup();
  const file = { folder: folder.id, path: "反馈表.xlsx" };
  const cells = [{ cell: "C2", value: "已补发" }, { cell: "D2", value: "42" }];
  const preview = await skills.run(store, "preview_edit", { file, cells });
  assert.deepEqual(preview.cells, [{ cell: "C2", before: "", after: "已补发" }, { cell: "D2", before: "", after: "42" }]);
  assert.ok(preview.overwrite_allowed && preview.sheet === "反馈");
  const original = await fs.readFile(path.join(base, "反馈表.xlsx"));
  const done = await skills.run(store, "apply_edit", { file, cells, expected_sha256: preview.sha256, mode: "save_as" });
  assert.equal(done.path, "反馈表（修改）.xlsx");
  assert.ok(done.verified);
  assert.deepEqual(await fs.readFile(path.join(base, "反馈表.xlsx")), original);  // 原文件没动
  const text = (await toText("x.xlsx", await fs.readFile(path.join(base, done.path)))).text;
  assert.match(text, /R2 \| A: Medan \| B: 延误 \| C: 已补发 \| D: 42/);
  assert.match(text, /R3 \| A: Jakarta \| B: 破损 \| C: 已赔付/);  // 别的格子不变
  assert.match(text, /E: 2/);  // 公式的结果保留
});

test("overwrite keeps a backup; a file changed after the preview is not touched", async () => {
  const { base, store, folder } = await setup();
  const file = { folder: folder.id, path: "反馈表.xlsx" };
  const cells = [{ cell: "C2", value: "已补发" }];
  const preview = await skills.run(store, "preview_edit", { file, cells });
  const original = await fs.readFile(path.join(base, "反馈表.xlsx"));
  const done = await skills.run(store, "apply_edit", { file, cells, expected_sha256: preview.sha256, mode: "overwrite" });
  assert.equal(done.path, "反馈表.xlsx");
  assert.match(done.backup, /^反馈表\.relay-backup-\d{12}\.xlsx$/);
  assert.deepEqual(await fs.readFile(path.join(base, done.backup)), original);  // 备份就是原文件
  assert.match((await toText("x.xlsx", await fs.readFile(path.join(base, "反馈表.xlsx")))).text, /C: 已补发/);
  // 用旧的预览再改一次：文件已经变了，不写
  const before = await fs.readFile(path.join(base, "反馈表.xlsx"));
  await assert.rejects(skills.run(store, "apply_edit", { file, cells: [{ cell: "C3", value: "x" }], expected_sha256: preview.sha256, mode: "overwrite" }),
    /预览之后被改过/);
  assert.equal(sha(await fs.readFile(path.join(base, "反馈表.xlsx"))), sha(before));
  await assert.rejects(skills.run(store, "preview_edit", { file, cells: [{ cell: "../A1", value: "x" }] }), /格子编号不对/);
});

test("a workbook with charts can only be saved as a new file", async () => {
  const { base, store, folder } = await setup();
  const zip = new PizZip(await fs.readFile(path.join(base, "反馈表.xlsx")));
  zip.file("xl/charts/chart1.xml", "<chartSpace/>");
  await fs.writeFile(path.join(base, "带图表.xlsx"), zip.generate({ type: "nodebuffer" }));
  const file = { folder: folder.id, path: "带图表.xlsx" };
  const preview = await skills.run(store, "preview_edit", { file, cells: [{ cell: "C2", value: "x" }] });
  assert.equal(preview.overwrite_allowed, false);
  assert.deepEqual(preview.risks, ["图表"]);
  await assert.rejects(skills.run(store, "apply_edit", { file, cells: [{ cell: "C2", value: "x" }], expected_sha256: preview.sha256, mode: "overwrite" }),
    /不能覆盖/);
});

function docx(paragraphs) {
  // 一个最小的 Word 文件；第一段的占位符故意拆成几段 run（Word 里经常这样），模板也要能认出来
  const zip = new PizZip();
  zip.file("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
    + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>');
  zip.file("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>');
  const body = paragraphs.map((runs) => `<w:p>${runs.map((t) => `<w:r><w:t xml:space="preserve">${t}</w:t></w:r>`).join("")}</w:p>`).join("");
  zip.file("word/document.xml", `<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body}</w:body></w:document>`);
  return zip.generate({ type: "nodebuffer" });
}

test("a Word template is filled into a new file and checked", async () => {
  const { base, store, folder } = await setup();
  await fs.writeFile(path.join(base, "周报模板.docx"), docx([["本周完成：", "{{本", "周完成}}"], ["下周计划：{{下周计划}}"], ["负责人：{{负责人}}"]]));
  const template = { folder: folder.id, path: "周报模板.docx" };
  assert.deepEqual((await skills.run(store, "template_fields", { template })).fields, ["本周完成", "下周计划", "负责人"]);
  await assert.rejects(skills.run(store, "fill_template", { template, values: { 本周完成: "x" }, output: { folder: folder.id, path: "周报" } }),
    /没有给内容：下周计划、负责人/);
  const result = await skills.run(store, "fill_template", { template, output: { folder: folder.id, path: "周报 第 44 周" },
    values: { 本周完成: ["Medan 延误复盘完成", "报价确认"], 下周计划: "上线新线路", 负责人: "Budi" } });
  assert.equal(result.output.path, "周报 第 44 周.docx");
  assert.ok(result.output.verified);
  const text = (await toText("x.docx", await fs.readFile(path.join(base, result.output.path)))).text;
  assert.match(text, /Medan 延误复盘完成/);
  assert.match(text, /负责人：Budi/);
  assert.doesNotMatch(text, /\{\{/);
  assert.match((await fs.readFile(path.join(base, "周报模板.docx"))).toString("utf8"), /周完成\}\}/);  // 模板本身没改
});

test("an Excel template keeps numbers as numbers", async () => {
  const { base, store, folder } = await setup();
  const book = new ExcelJS.Workbook();
  const ws = book.addWorksheet("周报");
  ws.addRows([["本周件量", "{{件量}}"], ["说明", "第 {{周次}} 周：{{说明}}"]]);
  await fs.writeFile(path.join(base, "模板.xlsx"), Buffer.from(await book.xlsx.writeBuffer()));
  const result = await skills.run(store, "fill_template", { template: { folder: folder.id, path: "模板.xlsx" },
    values: { 件量: 1280, 周次: "44", 说明: "Medan 恢复正常" }, output: { folder: folder.id, path: "周报.xlsx" } });
  assert.ok(result.output.verified);
  const out = new ExcelJS.Workbook();
  await out.xlsx.load(await fs.readFile(path.join(base, "周报.xlsx")));
  assert.equal(out.getWorksheet("周报").getCell("B1").value, 1280);
  assert.equal(out.getWorksheet("周报").getCell("B2").value, "第 44 周：Medan 恢复正常");
});
