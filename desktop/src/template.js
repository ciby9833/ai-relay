// 按模板生成文件（例如周报）：模板里写 {{本周完成}} 这样的占位符（Word 或 Excel），
// 助理把内容整理好交过来，这里填进去生成一个新文件（模板本身不改），再打开核对：没有留下占位符、给的内容都在。
// 每个占位符都要给值（可以是空字符串）；漏了的不生成，并列出来。

const path = require("node:path");
const Docxtemplater = require("docxtemplater");
const ExcelJS = require("exceljs");
const PizZip = require("pizzip");
const { read, write, FolderError } = require("./folders");
const { cell: cellText } = require("./parse");

const FIELD = /\{\{\s*([^{}]+?)\s*\}\}/g;

function kindOf(relative) {
  const ext = path.extname(relative).toLowerCase();
  if (ext === ".docx") return "docx";
  if (ext === ".xlsx") return "xlsx";
  throw new FolderError("模板只能是 Word（.docx）或 Excel（.xlsx）");
}

function docxText(data) {
  const doc = new Docxtemplater(new PizZip(data), { delimiters: { start: "{{", end: "}}" }, paragraphLoop: true, linebreaks: true });
  return doc.getFullText();
}

async function xlsxCells(data) {
  const book = new ExcelJS.Workbook();
  await book.xlsx.load(data);
  return book;
}

function fieldsIn(text) {
  return [...new Set([...text.matchAll(FIELD)].map((m) => m[1]))];
}

/** 模板里有哪些占位符。 */
async function templateFields(folders, input) {
  const kind = kindOf(input.template.path);
  const file = await read(folders.get(input.template.folder), input.template.path);
  let fields;
  if (kind === "docx") fields = fieldsIn(docxText(file.data));
  else {
    const book = await xlsxCells(file.data);
    const texts = [];
    book.eachSheet((ws) => ws.eachRow((row) => row.eachCell((c) => texts.push(cellText(c.value)))));
    fields = fieldsIn(texts.join("\n"));
  }
  return { fields, kind };
}

function asText(value) {
  return Array.isArray(value) ? value.map((v) => `• ${v}`).join("\n") : String(value ?? "");
}

/** 填模板，生成新文件，核对。 */
async function fillTemplate(folders, input) {
  const kind = kindOf(input.template.path);
  const { fields } = await templateFields(folders, input);
  const values = input.values || {};
  const missing = fields.filter((f) => !(f in values));
  if (missing.length) throw new FolderError(`模板里这些占位符没有给内容：${missing.join("、")}`);
  const file = await read(folders.get(input.template.folder), input.template.path);
  const filled = Object.fromEntries(fields.map((f) => [f, asText(values[f])]));
  let data;
  let check;
  if (kind === "docx") {
    const doc = new Docxtemplater(new PizZip(file.data), {
      delimiters: { start: "{{", end: "}}" }, paragraphLoop: true, linebreaks: true, nullGetter: () => "" });
    doc.render(filled);
    data = doc.getZip().generate({ type: "nodebuffer", compression: "DEFLATE" });
    check = docxText(data);
  } else {
    const book = await xlsxCells(file.data);
    book.eachSheet((ws) => ws.eachRow((row) => row.eachCell((c) => {
      const text = cellText(c.value);
      if (!FIELD.test(text)) return;
      FIELD.lastIndex = 0;
      const whole = text.match(/^\{\{\s*([^{}]+?)\s*\}\}$/);
      const raw = whole ? values[whole[1]] : null;
      c.value = whole && typeof raw === "number" ? raw : text.replace(FIELD, (_, name) => filled[name] ?? "");
    })));
    data = Buffer.from(await book.xlsx.writeBuffer());
    const texts = [];
    (await xlsxCells(data)).eachSheet((ws) => ws.eachRow((row) => row.eachCell((c) => texts.push(cellText(c.value)))));
    check = texts.join("\n");
  }
  // 核对：没有留下占位符；每段给的内容（取开头一小段）都在文件里
  const left = fieldsIn(check);
  const absent = fields.filter((f) => {
    const sample = asText(values[f]).split("\n")[0].trim().slice(0, 20);
    return sample && !check.replace(/\s+/g, " ").includes(sample.replace(/\s+/g, " ").replace(/ ⏎ /g, " "));
  });
  if (left.length) throw new FolderError(`生成的文件里还留着占位符：${left.join("、")}，没有保存`);
  const ext = path.extname(input.template.path);
  const saved = await write(folders.get(input.output.folder), input.output.path.endsWith(ext) ? input.output.path : `${input.output.path}${ext}`, data);
  return { output: { path: saved.path, verified: saved.verified && absent.length === 0 }, fields: fields.length, not_found_after_fill: absent };
}

module.exports = { templateFields, fillTemplate };
