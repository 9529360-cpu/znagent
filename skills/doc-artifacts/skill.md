---
name: doc-artifacts
description: "生成可交付的文档产物：.docx 报告、.xlsx 表格、.pptx 演示文稿，以及 Markdown 转 PDF。当用户说“写一份报告”“做个表格”“做个 PPT”“把这份 Markdown 转成 PDF”时使用。四次生成动作都要先经过用户的审批卡，生成后会自动回读校验（文件可打开、结构数量对得上）。"
version: 0.1.0
allowed-tools:
  - doc.generate_docx
  - doc.generate_xlsx
  - doc.generate_pptx
  - doc.generate_pdf
source: local
---

# 文档产物（docx / xlsx / pptx / PDF）

## 适用场景

- 用户要一份能发出去/存档的文档：报告、总结、表格、演示文稿、PDF。
- 用户给了一份 Markdown，要转成 PDF。

## 工具与模板

| 动作 | 产物 | 模板 | template_data |
| --- | --- | --- | --- |
| `doc.generate_docx` | .docx | `report` | title（必填）、author、summary、sections[{heading, paragraphs}]、tables[{caption, headers, rows}] |
| `doc.generate_xlsx` | .xlsx | `data_table` | sheets[{name, headers, rows}] |
| `doc.generate_pptx` | .pptx | `briefing_deck` | title（必填）、subtitle、slides[{title, bullets 或 body}]、closing |
| `doc.generate_pdf` | .pdf | （无，用 Markdown 直渲） | markdown（必填）、title |

`output_name` 是纯文件名（如 `周报.docx`，不带路径也可以，缺后缀会自动补）；`output_dir` 不传就用挂载时配好的目录。模板名写错、表格行列对不上、文件名带 `../` 都会显式报错，不要绕过去。

## 步骤

1. 按用户要的产物选动作，把内容整理成上表对应的结构。
2. 表格：每行的单元格数必须和表头一致，对不上就先问用户或补齐，不要猜。
3. 调用动作。第一次调用会弹出审批卡——等用户点了“允许”再继续；被拒绝就停下，不要换个名字重传。
4. 成功返回里带 `verification`：`expected` 是生成时报的结构（表数、行列数、页数），`observed` 是回读看到的结构，两边对得上才算交付。
5. 把文件路径和校验结果告诉用户。

## PDF 的边界（先说清楚）

- PDF 渲染器是仓库自带的极简实现，只支持 WinAnsi 字符（英文、数字、常用西文标点）。
- **中文、日文、emoji 等字符在 PDF 里会显式报错**，不是乱码——这是故意的。用户要中文 PDF 时，用 `doc.generate_docx` 生成 .docx 交付，并说明原因。
- 支持的 Markdown：`#`/`##`/`###` 标题、段落（含 `**加粗**`）、`-` 列表、`1.` 有序列表、`| 表 | 格 |`（必须有 `| --- |` 分隔行）、```` ``` ```` 代码块、`---` 分隔线。

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “输出目录就是个默认建议，写哪都一样。” | 审批卡上写明的目标路径是用户实际看到并批准的，换地方写等于交付了用户没看过的东西。目录不对就先问。 |
| “表格有一行少了个单元格，我按表头补个空字符串。” | 空单元格可以补，但“这行本来有几列”不能猜——先确认，行列对不上必须显式报错。 |
| “PDF 里中文报错了，我把中文删掉再渲一张。” | 删用户内容等于篡改交付物。中文走 docx 通道，并告诉用户为什么。 |
| “审批被拒只是这次没通过，条件不变再交一次也许就过了。” | 拒绝针对的是这次生成意图本身。改条件重交前，先跟用户确认要改什么。 |
| “verification 里页数对不上，但文件能打开，就这样吧。” | 页数/表数对不上说明生成或回读有一边错了，必须查清再交付，不能“差不多”。 |

## References

- 实现与校验逻辑：`runtime/python/zn_agent/core/doc_artifacts_connector.py`（`build_*`/`write_*`/`verify_*`，`attach_doc_artifact_tools`，`register_doc_artifacts_runtime`）。
- 测试：`tests/zn_agent/core/test_doc_artifacts_connector.py`（四类产物生成+回读、坏参数显式失败、审批拒绝/允许、重放拒绝、skill evals）。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R8 条目。
