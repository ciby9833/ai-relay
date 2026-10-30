// 本机技能：固定的、测试过的处理步骤，在这台 Mac 上对授权文件夹里的文件做加工。
// 技能的名字和输入输出由服务器定义（backend/app/skills.py）；这里只实现，不认识的技能一律拒绝。
// 原文件只读；结果总是写成新文件（同名自动换名，不覆盖），写完重新打开核对。
// 回传给云端的只有数字和少量示例（给助理解释用），不回传整张表。

const ExcelJS = require("exceljs");
const path = require("node:path");
const { read, write, FolderError } = require("./folders");
const { csvRows, cell } = require("./parse");

const EXAMPLES = 10;
const MAX_ROWS = 200_000;

/** 读一张表：表头（第一行非空行）+ 数据行（数组）。支持 xlsx / csv。 */
async function loadTable(folder, relative, sheetName) {
  const file = await read(folder, relative);
  const ext = path.extname(relative).toLowerCase();
  let rows;
  let sheet = null;
  if (ext === ".csv") {
    rows = csvRows(file.data.toString("utf8").replace(/^﻿/, ""));
  } else if (ext === ".xlsx" || ext === ".xlsm") {
    const book = new ExcelJS.Workbook();
    await book.xlsx.load(file.data);
    const ws = sheetName ? book.getWorksheet(sheetName) : book.worksheets.find((w) => w.state === "visible") || book.worksheets[0];
    if (!ws) throw new FolderError(`找不到工作表「${sheetName}」`);
    sheet = ws.name;
    rows = [];
    ws.eachRow({ includeEmpty: false }, (row) => {
      const values = [];
      for (let c = 1; c <= ws.columnCount; c += 1) values.push(cell(row.getCell(c).value));
      rows.push(values);
    });
  } else {
    throw new FolderError("只能处理 Excel（.xlsx）和 CSV 文件");
  }
  rows = rows.map((r) => r.map((v) => String(v ?? "").trim())).filter((r) => r.some(Boolean));
  if (rows.length > MAX_ROWS) throw new FolderError(`表太大（超过 ${MAX_ROWS} 行）`);
  if (!rows.length) throw new FolderError(`「${relative}」是空的`);
  const headers = rows[0].map((h, i) => h || `第${i + 1}列`);
  return { headers, rows: rows.slice(1), sheet, version: { size: file.size, modified: file.modified } };
}

function columnIndex(headers, name, label) {
  const i = headers.findIndex((h) => h === name);
  if (i < 0) throw new FolderError(`「${label}」里没有“${name}”这一列（有：${headers.slice(0, 12).join("、")}）`);
  return i;
}

function number(value) {
  const n = Number(String(value).replace(/,/g, ""));
  return value !== "" && Number.isFinite(n) ? n : null;
}

async function saveWorkbook(folder, relative, sheets) {
  const book = new ExcelJS.Workbook();
  for (const { name, headers, rows } of sheets) {
    const ws = book.addWorksheet(name.slice(0, 31));
    ws.addRow(headers);
    ws.getRow(1).font = { bold: true };
    for (const row of rows) ws.addRow(row);
    ws.columns.forEach((col) => { col.width = 16; });
  }
  const data = Buffer.from(await book.xlsx.writeBuffer());
  const saved = await write(folder, relative.endsWith(".xlsx") ? relative : `${relative}.xlsx`, data);
  // 重新打开核对：每个工作表的行数和写进去的一样
  const check = new ExcelJS.Workbook();
  await check.xlsx.load(require("node:fs").readFileSync(saved.full));
  const ok = sheets.every(({ name, rows }) => {
    const ws = check.getWorksheet(name.slice(0, 31));
    return ws && ws.actualRowCount === rows.length + 1;
  });
  return { path: saved.path, verified: saved.verified && ok };
}

/** 对比两张表：按关键列找出新增、删除、变化（哪一列从什么变成什么）。 */
async function compareTables(folders, input) {
  const left = await loadTable(folders.get(input.left.folder), input.left.path, input.left.sheet);
  const right = await loadTable(folders.get(input.right.folder), input.right.path, input.right.sheet);
  const lk = columnIndex(left.headers, input.key, input.left.path);
  const rk = columnIndex(right.headers, input.key, input.right.path);
  const index = (table, k) => {
    const map = new Map();
    const duplicates = new Set();
    for (const row of table.rows) {
      const key = row[k];
      if (!key) continue;
      if (map.has(key)) duplicates.add(key);
      map.set(key, row);
    }
    return { map, duplicates };
  };
  const a = index(left, lk);
  const b = index(right, rk);
  const shared = left.headers.filter((h) => right.headers.includes(h) && h !== input.key);
  const added = [...b.map.keys()].filter((k) => !a.map.has(k));
  const removed = [...a.map.keys()].filter((k) => !b.map.has(k));
  const changes = [];
  for (const [key, row] of a.map) {
    const other = b.map.get(key);
    if (!other) continue;
    for (const h of shared) {
      const before = row[left.headers.indexOf(h)] ?? "";
      const after = other[right.headers.indexOf(h)] ?? "";
      const x = number(before);
      const y = number(after);
      const same = x !== null && y !== null ? Math.abs(x - y) < 1e-9 : before === after;
      if (!same) changes.push([key, h, before, after]);
    }
  }
  const output = await saveWorkbook(folders.get(input.output.folder), input.output.path, [
    { name: "汇总", headers: ["项目", "数量"], rows: [["左表行数", left.rows.length], ["右表行数", right.rows.length], ["新增", added.length],
      ["删除", removed.length], ["有变化的格子", changes.length], ["左表重复的关键值", a.duplicates.size], ["右表重复的关键值", b.duplicates.size]] },
    { name: "新增", headers: right.headers, rows: added.map((k) => b.map.get(k)) },
    { name: "删除", headers: left.headers, rows: removed.map((k) => a.map.get(k)) },
    { name: "变化", headers: [input.key, "列", "原来", "现在"], rows: changes },
  ]);
  return {
    output, counts: { left_rows: left.rows.length, right_rows: right.rows.length, added: added.length, removed: removed.length,
      changed_cells: changes.length, changed_rows: new Set(changes.map((c) => c[0])).size,
      duplicate_keys: a.duplicates.size + b.duplicates.size },
    compared_columns: shared,
    examples: { added: added.slice(0, EXAMPLES), removed: removed.slice(0, EXAMPLES),
      changed: changes.slice(0, EXAMPLES).map(([key, column, before, after]) => ({ key, column, before, after })) },
    sources: { left: { ...input.left, sheet: left.sheet, ...left.version }, right: { ...input.right, sheet: right.sheet, ...right.version } },
  };
}

/** 汇总一张表：按某几列分组，计行数，并对数值列求和。 */
async function summarizeTable(folders, input) {
  const table = await loadTable(folders.get(input.source.folder), input.source.path, input.source.sheet);
  const groupBy = (input.group_by || []).map((name) => columnIndex(table.headers, name, input.source.path));
  const sums = (input.sum || []).map((name) => columnIndex(table.headers, name, input.source.path));
  const groups = new Map();
  let skipped = 0;
  for (const row of table.rows) {
    const key = groupBy.map((i) => row[i] || "（空）");
    const id = JSON.stringify(key);
    if (!groups.has(id)) groups.set(id, { key, count: 0, sums: sums.map(() => 0) });
    const g = groups.get(id);
    g.count += 1;
    sums.forEach((i, n) => {
      const v = number(row[i]);
      if (v === null && row[i]) skipped += 1;
      else if (v !== null) g.sums[n] += v;
    });
  }
  const rows = [...groups.values()].sort((x, y) => y.count - x.count)
    .map((g) => [...g.key, g.count, ...g.sums.map((v) => Math.round(v * 100) / 100)]);
  const headers = [...(input.group_by || []), "行数", ...(input.sum || []).map((h) => `${h}合计`)];
  const totals = ["合计", ...Array(Math.max(0, groupBy.length - 1)).fill(""), table.rows.length,
    ...sums.map((_, n) => Math.round([...groups.values()].reduce((s, g) => s + g.sums[n], 0) * 100) / 100)];
  const output = await saveWorkbook(folders.get(input.output.folder), input.output.path, [
    { name: "汇总", headers, rows: groupBy.length ? [...rows, totals] : [totals] },
  ]);
  return { output, rows: table.rows.length, groups: groups.size, non_numeric_skipped: skipped, headers,
    top: rows.slice(0, 20), totals, source: { ...input.source, sheet: table.sheet, ...table.version } };
}

const edit = require("./edit");
const template = require("./template");

const SKILLS = {
  compare_tables: compareTables, summarize_table: summarizeTable,
  preview_edit: edit.previewEdit, apply_edit: edit.applyEdit,
  template_fields: template.templateFields, fill_template: template.fillTemplate,
};

/** 执行一个技能：只认这里实现了的；输入里的每个文件夹都要在授权列表里（读 / 写权限由 folders 再查一次）。 */
async function run(folders, name, input) {
  const skill = SKILLS[name];
  if (!skill) throw new FolderError(`这台 Mac 的客户端不认识技能「${name}」，请更新客户端`);
  return skill(folders, input || {});
}

module.exports = { run, SKILLS, loadTable };
