// 修改已有的 Excel 文件：先预览（读出每个要改的格子现在的值和文件版本），本人确认后再写。
//   默认另存为新文件；只有他明确选了“覆盖原文件”才覆盖，覆盖前先在同一个文件夹里留一份备份。
//   写之前核对文件版本和预览时一样（没被改过）；写完重新打开核对：要改的格子是新值，其他每个格子和原来一模一样。
//   文件里有图表、数据透视表、图片、宏这类内容时，重写可能丢失它们：只允许另存，不允许覆盖。

const crypto = require("node:crypto");
const path = require("node:path");
const ExcelJS = require("exceljs");
const PizZip = require("pizzip");
const { read, write, replace, FolderError } = require("./folders");
const { cell: cellText } = require("./parse");

const REF = /^([A-Z]{1,3})([1-9]\d{0,6})$/;
const RISKY = [
  [/^xl\/charts\//, "图表"], [/^xl\/pivotTables\//, "数据透视表"], [/^xl\/drawings\//, "图片或形状"],
  [/^xl\/vbaProject\.bin$/, "宏"], [/^xl\/externalLinks\//, "外部链接"], [/^xl\/slicers\//, "切片器"],
];

function sha(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function risks(data) {
  const names = Object.keys(new PizZip(data).files);
  return [...new Set(RISKY.filter(([re]) => names.some((n) => re.test(n))).map(([, label]) => label))];
}

function checkCells(cells) {
  if (!Array.isArray(cells) || !cells.length || cells.length > 500) throw new FolderError("要改 1 到 500 个格子");
  for (const c of cells) if (!REF.test(String(c.cell || ""))) throw new FolderError(`格子编号不对：${c.cell}（例如 B3）`);
}

async function open(file, sheetName) {
  const book = new ExcelJS.Workbook();
  await book.xlsx.load(file);
  const sheet = sheetName ? book.getWorksheet(sheetName) : book.worksheets.find((w) => w.state === "visible") || book.worksheets[0];
  if (!sheet) throw new FolderError(`找不到工作表「${sheetName}」`);
  return { book, sheet };
}

function excelOnly(relative) {
  if (![".xlsx", ".xlsm"].includes(path.extname(relative).toLowerCase())) throw new FolderError("目前只能修改 Excel（.xlsx）文件");
}

/** 预览：每个格子现在的值、文件版本、能不能覆盖。 */
async function previewEdit(folders, input) {
  excelOnly(input.file.path);
  checkCells(input.cells);
  const file = await read(folders.get(input.file.folder), input.file.path);
  const { sheet } = await open(file.data, input.file.sheet);
  const found = risks(file.data);
  return {
    sheet: sheet.name, sha256: sha(file.data), size: file.size, modified: file.modified,
    cells: input.cells.map((c) => ({ cell: c.cell, before: cellText(sheet.getCell(c.cell).value), after: c.value })),
    overwrite_allowed: found.length === 0, risks: found,
  };
}

function snapshot(book) {
  const out = new Map();
  book.eachSheet((ws) => ws.eachRow({ includeEmpty: false }, (row, r) => row.eachCell({ includeEmpty: false }, (c, col) => {
    out.set(`${ws.name}!${col}:${r}`, cellText(c.value));
  })));
  return out;
}

function value(raw) {
  if (typeof raw === "number") return raw;
  const text = String(raw ?? "");
  return /^-?\d+(\.\d+)?$/.test(text.trim()) ? Number(text) : text;
}

/** 执行：版本核对 → 改 → 自查（要改的是新值，其他格子不变）→ 另存或覆盖（先备份）→ 读回核对。 */
async function applyEdit(folders, input) {
  excelOnly(input.file.path);
  checkCells(input.cells);
  const folder = folders.get(input.file.folder);
  const original = await read(folder, input.file.path);
  if (sha(original.data) !== input.expected_sha256) throw new FolderError("这个文件在预览之后被改过了，没有写入；请重新预览");
  const found = risks(original.data);
  if (input.mode === "overwrite" && found.length) {
    throw new FolderError(`文件里有${found.join("、")}，重写可能丢失，不能覆盖；请改为另存`);
  }
  const before = snapshot((await open(original.data, input.file.sheet)).book);
  const { book, sheet } = await open(original.data, input.file.sheet);
  for (const c of input.cells) sheet.getCell(c.cell).value = value(c.value);
  const data = Buffer.from(await book.xlsx.writeBuffer());
  // 自查：重新打开写出来的内容，要改的格子是新值，其他每个格子和原来一样
  const after = snapshot((await open(data)).book);
  const edited = new Set(input.cells.map((c) => {
    const [, colLetters, row] = c.cell.match(REF);
    let col = 0;
    for (const ch of colLetters) col = col * 26 + ch.charCodeAt(0) - 64;
    return `${sheet.name}!${col}:${row}`;
  }));
  for (const [key, text] of before) {
    if (!edited.has(key) && after.get(key) !== text) throw new FolderError(`写出来的文件里 ${key} 变了（${text} → ${after.get(key)}），没有写入`);
  }
  const reopened = (await open(data, sheet.name)).sheet;
  for (const c of input.cells) {
    if (cellText(reopened.getCell(c.cell).value) !== cellText(value(c.value))) throw new FolderError(`${c.cell} 没写成新值，没有写入`);
  }
  const ext = path.extname(input.file.path);
  const base = input.file.path.slice(0, -ext.length);
  if (input.mode === "overwrite") {
    const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
    const backup = await write(folder, `${base}.relay-backup-${stamp}${ext}`, original.data);
    const saved = await replace(folder, input.file.path, data, input.expected_sha256);
    return { mode: "overwrite", path: saved.path, backup: backup.path, verified: saved.verified, changed: input.cells.length };
  }
  const saved = await write(folder, input.output_path || `${base}（修改）${ext}`, data);
  return { mode: "save_as", path: saved.path, verified: saved.verified, changed: input.cells.length };
}

module.exports = { previewEdit, applyEdit, risks };
