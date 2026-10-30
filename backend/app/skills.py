"""本机技能的定义（放在服务端：名字、输入、输出、需要的客户端版本）。实现在 Mac 客户端（desktop/src/skills.js）。

技能是固定的、测试过的处理步骤，不是任意脚本：客户端只执行它认识的技能，云端只发这里定义过的技能。
输入里的每个文件都在授权文件夹里（读），输出写进授权写入的文件夹（只新建、不覆盖、写完核对）。
回传给云端的只有数字和少量示例，不回传整张表。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    name: str
    title: str
    min_client: str  # 需要的 Mac 客户端最低版本
    reads: tuple[str, ...]  # 输入里哪些文件要读（{folder, path, sheet?}）：文件夹要有读权限
    writes: tuple[str, ...]  # 输入里哪些位置要写（{folder, path}）：文件夹要有写权限（可以和 reads 是同一个，例如改已有文件）
    returns: str  # 回传什么


SKILLS = {s.name: s for s in [
    Skill("compare_tables", "对比两张表", "0.2.0", ("left", "right"), ("output",),
          "两张表的行数、新增 / 删除 / 变化的数量、最多 10 条示例、参与对比的列、生成的对比文件（核对结果）"),
    Skill("summarize_table", "汇总一张表", "0.2.0", ("source",), ("output",),
          "总行数、分组数、前 20 组、合计、生成的汇总文件（核对结果）"),
    Skill("preview_edit", "预览修改 Excel", "0.3.0", ("file",), (),
          "每个要改的格子现在的值、文件版本（sha256）、能不能覆盖（有图表 / 透视表 / 图片 / 宏时不能）"),
    Skill("apply_edit", "执行修改 Excel", "0.3.0", ("file",), ("file",),
          "另存的新文件或覆盖后的文件、备份文件（覆盖时）、核对结果；文件在预览后被改过则不写"),
    Skill("template_fields", "查看模板的占位符", "0.3.0", ("template",), (), "模板里的占位符列表"),
    Skill("fill_template", "按模板生成文件", "0.3.0", ("template",), ("output",),
          "生成的新文件（核对：没有留下占位符、给的内容都在）"),
]}


def version_tuple(value: str | None) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in (value or "0").split(".")[:3])
    except ValueError:
        return (0,)


def supported(skill: Skill, app_version: str | None) -> bool:
    return version_tuple(app_version) >= version_tuple(skill.min_client)
