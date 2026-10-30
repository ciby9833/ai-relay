// 在 Mac 上把文件解析成文字：只把文字（带定位）送去给助理，原文件不离开这台电脑。
// 格式和服务器的解析一致（backend/app/sources/files.py），引用时能直接定位：
//   Excel / CSV：每个工作表一段，每行 `R行号 | 列字母: 值`，空格子跳过；
//   PDF：按页 `## 第 n 页`；Word：按段落，表格行用 `| … |`。
// 解析不了的格式（例如 .doc、.pptx、扫描件 PDF）抛出 Unsupported，由调用方改为上传到服务器解析。

const path = require("node:path");

const CELL_CHARS = 300;

class Unsupported extends Error {}

function cell(value) {
  if (value === null || value === undefined) return "";
  let text;
  if (value instanceof Date) text = value.toISOString().slice(0, 10);
  else if (typeof value === "object") {
    if ("result" in value) text = value.result === undefined ? "" : String(value.result); // 公式：用计算结果
    else if ("richText" in value) text = value.richText.map((r) => r.text).join("");
    else if ("text" in value) text = String(value.text);
    else if ("error" in value) text = String(value.error);
    else text = "";
  } else text = String(value);
  text = text.trim().replace(/\s*\n\s*/g, " ⏎ ");
  return text.length <= CELL_CHARS ? text : `${text.slice(0, CELL_CHARS)}…`;
}

function column(n) {
  let s = "";
  for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) s = String.fromCharCode(65 + ((x - 1) % 26)) + s;
  return s;
}

async function xlsx(data) {
  const ExcelJS = require("exceljs");
  const book = new ExcelJS.Workbook();
  try {
    await book.xlsx.load(data);
  } catch (error) {
    throw new Unsupported(`无法解析这个 Excel 文件：${error.message}`);
  }
  const parts = [];
  book.eachSheet((sheet) => {
    const merged = new Map((sheet.model.merges || []).map((range) => [range.split(":")[0], range]));
    const rows = [];
    sheet.eachRow({ includeEmpty: false }, (row, rowNumber) => {
      const cells = [];
      row.eachCell({ includeEmpty: false }, (c, col) => {
        const text = cell(c.value);
        if (!text) return;
        const ref = `${column(col)}${rowNumber}`;
        cells.push(`${column(col)}${merged.has(ref) ? `（合并 ${merged.get(ref)}）` : ""}: ${text}`);
      });
      if (cells.length) rows.push(`R${rowNumber} | ${cells.join(" | ")}`);
    });
    const hidden = sheet.state && sheet.state !== "visible" ? "（隐藏）" : "";
    parts.push(`## 工作表「${sheet.name}」${hidden}，共 ${sheet.rowCount} 行 ${sheet.columnCount} 列\n${rows.join("\n") || "（空）"}`);
  });
  return parts.join("\n\n");
}

function csvRows(text) {
  // 标准 CSV：引号里可以有逗号、换行，"" 表示一个引号
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += ch;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows;
}

function csv(data) {
  const rows = csvRows(data.toString("utf8").replace(/^﻿/, ""));
  return rows.map((row, i) => [i + 1, row]).filter(([, row]) => row.some((v) => v.trim()))
    .map(([n, row]) => `R${n} | ${row.map((v, j) => [column(j + 1), cell(v)]).filter(([, v]) => v).map(([c, v]) => `${c}: ${v}`).join(" | ")}`)
    .join("\n");
}

async function pdf(data) {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  let doc;
  try {
    // 标准字体数据随 pdfjs-dist 一起打包：没有它，用标准字体的 PDF 文字可能提取不全
    const fonts = `${path.join(path.dirname(require.resolve("pdfjs-dist/package.json")), "standard_fonts")}${path.sep}`;
    doc = await pdfjs.getDocument({ data: new Uint8Array(data), isEvalSupported: false, disableFontFace: true, useSystemFonts: false,
      standardFontDataUrl: fonts }).promise;
  } catch (error) {
    throw new Unsupported(`无法解析这个 PDF：${error.message}`);
  }
  const pages = [];
  for (let n = 1; n <= doc.numPages; n += 1) {
    const page = await doc.getPage(n);
    const content = await page.getTextContent();
    let text = "";
    for (const item of content.items) text += item.str + (item.hasEOL ? "\n" : "");
    pages.push(`## 第 ${n} 页\n${text.trim()}`);
  }
  const text = pages.join("\n\n");
  if (text.replace(/\s|## 第 \d+ 页/g, "").length < 20) throw new Unsupported("这个 PDF 没有可提取的文字（可能是扫描件）");
  return text;
}

async function docx(data) {
  const mammoth = require("mammoth");
  try {
    const result = await mammoth.extractRawText({ buffer: data });
    return result.value.replace(/\n{3,}/g, "\n\n").trim();
  } catch (error) {
    throw new Unsupported(`无法解析这个 Word 文件：${error.message}`);
  }
}

/** 解析成文字；返回 { text, kind }。不支持的格式抛 Unsupported。 */
async function toText(filename, data) {
  const ext = path.extname(filename).toLowerCase().slice(1);
  if (ext === "xlsx" || ext === "xlsm") return { kind: "xlsx", text: await xlsx(data) };
  if (ext === "csv") return { kind: "csv", text: csv(data) };
  if (ext === "pdf") return { kind: "pdf", text: await pdf(data) };
  if (ext === "docx") return { kind: "docx", text: await docx(data) };
  if (["txt", "md", "json", "log"].includes(ext)) return { kind: "txt", text: data.toString("utf8") };
  throw new Unsupported(`这台 Mac 上还不能解析 .${ext} 文件`);
}

module.exports = { toText, csvRows, cell, column, Unsupported };
