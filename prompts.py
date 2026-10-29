"""Section definitions and default prompt templates for the proposal agent.

Every template may use these placeholders (filled in by agent.fill_prompt):
    {guideline_summary}  structured summary extracted from the funding guideline
    {project_idea}       the applicant's title and short description
    {previous_sections}  the sections already written, in order
    {language}           output language, "中文" or "English"

Placeholders are replaced literally, so users can type other braces in the UI
without breaking anything.
"""

# Shared rules sent as the system prompt for every section.
SYSTEM_PROMPT = """你是一名资深的科研项目申报书撰写专家，熟悉国家自然科学基金（NSFC）及省部级科研项目的申报要求与评审标准。
You are an expert grant writer for NSFC and provincial research programmes.

必须遵守的规则 / Hard rules:
1. 不得编造参考文献、作者、期刊、DOI、统计数据或实验结果。需要引用时写"[待补充文献]"，需要数据时写"[待补充数据]"。
   Never invent citations, statistics or results; use "[待补充文献]" / "[待补充数据]" placeholders instead.
2. 只能提及真实存在、广为人知的数据集、基准、评价指标和模型（如 ImageNet、GoPro、DAVIS、PSNR、SSIM、LPIPS）。
   不确定某个名称是否真实存在时，不要写出该名称，改写为"[待补充数据集]"或用通用描述（如"公开的视频去模糊数据集"）。
   Only name datasets, benchmarks, metrics and models you are certain exist; if unsure, write "[待补充数据集]" or describe it generically.
3. 经费预算总额不得超过指南规定的资助上限；指南未给出上限时，明确标注"[请依据指南核定]"。
   The budget total must not exceed the guideline's cap.
4. 进度安排必须与指南规定的项目执行期限完全一致。
   The timeline must match the project duration exactly.
5. 每一部分都必须紧扣指南中的资助方向和优先领域，并与已写章节保持一致（术语、目标、技术路线不得相互矛盾）。
   Every section must respect the guideline's priority areas and stay consistent with earlier sections.
6. 遵守指南规定的字数或篇幅限制。Respect any word or page limits.
7. 只输出该章节正文，不要输出寒暄、解释或章节总标题。可使用"### 小标题"、"- 列表"和 Markdown 表格。
   Output only the section body. You may use "### subheadings", "- bullets" and Markdown tables."""

SECTIONS = {
    "background": {
        "title": "立项依据",
        "title_en": "Background and Significance",
        "prompt": """请撰写申报书的"立项依据"部分（研究意义、国内外研究现状及发展动态分析）。

【项目指南摘要】
{guideline_summary}

【项目设想】
{project_idea}

【已完成章节】
{previous_sections}

要求：
- 从国家需求和学科前沿两方面论述研究意义，并明确说明与指南资助方向的对应关系；
- 归纳国内外研究现状，指出现有方法的主要不足和尚未解决的关键科学问题；
- 引出本项目拟解决的问题，自然过渡到研究目标；
- 涉及具体文献时一律使用"[待补充文献]"占位，不得编造作者、年份或数据；
- 篇幅约 1500–2500 字（或按指南限制）。
请使用{language}撰写。""",
    },
    "objectives": {
        "title": "研究目标",
        "title_en": "Research Objectives",
        "prompt": """请撰写申报书的"研究目标"部分。

【项目指南摘要】
{guideline_summary}

【项目设想】
{project_idea}

【已完成章节】
{previous_sections}

要求：
- 给出 1 个总体目标和 3–4 个具体、可检验的分目标；
- 目标须回应立项依据中提出的关键科学问题，并落在指南的优先领域内；
- 避免空泛表述，每个分目标应能在项目期限内完成并有可衡量的标志；
- 篇幅约 300–600 字。
请使用{language}撰写。""",
    },
    "content": {
        "title": "研究内容",
        "title_en": "Research Content",
        "prompt": """请撰写申报书的"研究内容"部分。

【项目指南摘要】
{guideline_summary}

【项目设想】
{project_idea}

【已完成章节】
{previous_sections}

要求：
- 围绕研究目标划分 3–4 项研究内容，每项使用"### 研究内容一：……"作为小标题；
- 每项说明要研究什么、解决哪个关键问题、与哪个分目标对应；
- 研究内容之间要有逻辑递进关系；
- 最后单独列出"### 拟解决的关键科学问题"（2–3 条）；
- 篇幅约 1200–2000 字。
请使用{language}撰写。""",
    },
    "methodology": {
        "title": "研究方案与技术路线",
        "title_en": "Methodology and Technical Route",
        "prompt": """请撰写申报书的"研究方案与技术路线"部分（含研究方法、技术路线、实验手段、可行性分析）。

【项目指南摘要】
{guideline_summary}

【项目设想】
{project_idea}

【已完成章节】
{previous_sections}

要求：
- 针对每一项研究内容给出具体的研究方法和实验设计（模型结构、数据集、评价指标等）；
- 用文字描述整体技术路线（可用"阶段一 → 阶段二 → ……"的形式），便于后期绘制技术路线图；
- 最后给出"### 可行性分析"，从理论基础、技术条件、研究团队与前期工作等方面论证；前期成果用"[待补充前期成果]"占位；
- 不得编造实验结果或性能数字；
- 篇幅约 1500–2500 字。
请使用{language}撰写。""",
    },
    "innovations": {
        "title": "创新点",
        "title_en": "Innovations",
        "prompt": """请撰写申报书的"特色与创新之处"部分。

【项目指南摘要】
{guideline_summary}

【项目设想】
{project_idea}

【已完成章节】
{previous_sections}

要求：
- 提炼 2–3 条创新点，分别从科学问题、方法或应用角度阐述；
- 每条说明与现有工作的本质区别，必须能在前文研究内容和方案中找到对应；
- 不夸大，不使用"国际首创""填补空白"等无法证实的表述；
- 篇幅约 400–800 字。
请使用{language}撰写。""",
    },
    "timeline": {
        "title": "进度安排",
        "title_en": "Timeline",
        "prompt": """请撰写申报书的"年度研究计划/进度安排"部分。

【项目指南摘要】
{guideline_summary}

【项目设想】
{project_idea}

【已完成章节】
{previous_sections}

要求：
- 总时长必须严格等于指南摘要中的"项目执行期限"；若指南未给出，按 4 年执行期并注明"[请依据指南核定执行期]"；
- 按年度（或半年）列出时间段、主要任务和阶段性成果，使用 Markdown 表格（列：时间段 | 主要研究任务 | 阶段性目标/成果）；
- 任务须覆盖前文全部研究内容，顺序与技术路线一致；
- 表格后用一两句话说明进度控制措施。
请使用{language}撰写。""",
    },
    "outcomes": {
        "title": "预期成果",
        "title_en": "Expected Outcomes",
        "prompt": """请撰写申报书的"预期研究成果"部分。

【项目指南摘要】
{guideline_summary}

【项目设想】
{project_idea}

【已完成章节】
{previous_sections}

要求：
- 分为理论成果、技术/软件成果、论文与专利、人才培养等方面；
- 成果数量要与项目期限、经费规模相匹配，表述务实（如"发表高水平学术论文 4–6 篇"），不得编造已有成果；
- 与进度安排中的阶段性成果保持一致；
- 篇幅约 300–600 字。
请使用{language}撰写。""",
    },
    "budget": {
        "title": "经费预算",
        "title_en": "Budget",
        "prompt": """请撰写申报书的"经费预算说明"部分。

【项目指南摘要】
{guideline_summary}

【项目设想】
{project_idea}

【已完成章节】
{previous_sections}

要求：
- 预算总额不得超过指南摘要中的"资助上限"；若指南未给出上限，所有金额后注明"[请依据指南核定]"；
- 按 NSFC 常用科目编制 Markdown 表格（列：预算科目 | 金额（万元） | 测算依据），科目包括：设备费、业务费（材料/测试化验加工/燃料动力/差旅/会议/国际合作交流/出版/文献/信息传播/知识产权事务等）、劳务费、专家咨询费、间接费用；
- 表格最后一行为"合计"，并核对各项之和等于合计且不超过上限；
- 每项测算依据须与研究方案中的实验需求对应，例如 GPU 服务器、数据标注等；
- 表格后简要说明预算的合理性。
请使用{language}撰写。""",
    },
}

SECTION_ORDER = [
    "background",
    "objectives",
    "content",
    "methodology",
    "innovations",
    "timeline",
    "outcomes",
    "budget",
]

# Prompt used by agent.analyse_guideline; the JSON shape is enforced by a schema.
ANALYSE_PROMPT = """下面是一份科研项目申报指南的全文。请仔细阅读并提取结构化信息。
只根据指南原文提取，指南中没有提到的字段填写"未说明"（列表字段返回空列表），不要推测或编造。
请使用{language}填写各字段。

<guideline>
{guideline_text}
</guideline>"""

EXAMPLE_IDEA_TITLE = "面向复杂退化场景的深度学习图像与视频复原方法研究"
EXAMPLE_IDEA_TEXT = """针对低光照、运动模糊、噪声与压缩伪影等复合退化下的图像与视频质量下降问题，
研究基于扩散模型与时空 Transformer 的统一复原框架：
1）构建退化感知的先验表示，实现对未知复合退化的自适应建模；
2）设计时空一致性约束，解决视频复原中的闪烁与时序不一致问题；
3）研究轻量化推理方法，使模型可部署于无人机和移动端等资源受限平台。
预期在公开数据集与实际应用场景中验证方法的有效性。"""
