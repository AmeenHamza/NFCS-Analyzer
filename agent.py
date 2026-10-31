"""LLM logic built on LangChain (Groq models).

- ChatGroq is the model; ChatPromptTemplate builds the messages.
- The guideline summary uses with_structured_output (a Pydantic schema).
- Each section is a prompt | model chain, streamed into the UI.
- The budget's arithmetic is recalculated in plain Python, not by the model.
"""

import io
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import docx
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from prompts import ANALYSE_PROMPT, SECTION_ORDER, SECTIONS, SYSTEM_PROMPT

load_dotenv()

# qwen/qwen3.8-27b writes good Chinese but is capped at 1,000 output tokens per
# minute on the free tier, which is less than one section, so it isn't offered.
MODELS = {
    "GPT-OSS 120B（推荐 recommended）": "openai/gpt-oss-120b",
    "GPT-OSS 20B（更快 faster）": "openai/gpt-oss-20b",
}
DEFAULT_MODEL = "openai/gpt-oss-120b"

# Groq's free tier allows 8,000 tokens per minute, and one request (input +
# max_tokens) must fit inside that. Budgets below are derived from it.
TOKEN_LIMIT = int(os.getenv("GROQ_TOKEN_LIMIT", "8000"))
TOKENS_PER_CHAR = 0.6           # measured ~0.5 on Chinese prompts; kept a little higher
SAFETY_TOKENS = 400
SECTION_MAX_TOKENS = 3500       # output budget for one section
ANALYSE_MAX_TOKENS = 2000       # output budget for one guideline chunk


def has_api_key() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _model_options(model: str) -> dict:
    """Keep reasoning short so the token budget goes to the answer."""
    if model.startswith("qwen/"):
        return {"reasoning_format": "hidden", "reasoning_effort": "none"}
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low"}
    return {}


@lru_cache(maxsize=16)
def get_llm(model: str, temperature: float, max_tokens: int) -> ChatGroq:
    """One ChatGroq per setting. max_retries waits out per-minute rate limits."""
    return ChatGroq(model=model, temperature=temperature, max_tokens=max_tokens,
                    max_retries=8, **_model_options(model))  # reads GROQ_API_KEY


def _chars_for(tokens: int) -> int:
    return max(0, int(tokens / TOKENS_PER_CHAR))


# ---------------------------------------------------------------- guideline

def load_guideline(file) -> str:
    """Read a guideline from a path or an uploaded file object (PDF, DOCX, TXT/MD)."""
    if isinstance(file, (str, Path)):
        name = str(file)
        data = Path(file).read_bytes()
    else:  # Streamlit UploadedFile or any object with .name and .read()
        name = getattr(file, "name", "upload.txt")
        data = file.read()

    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        text = "\n".join(parts)
    else:
        for encoding in ("utf-8", "gb18030"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", errors="ignore")

    text = text.strip()
    if not text:
        raise ValueError("No text could be extracted. If this is a scanned PDF, "
                         "run OCR first or paste the text instead.")
    return text


class GuidelineSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    programme_name: str = Field(description="项目/计划名称 Programme name")
    funding_goals: str = Field(description="资助目标 Funding goals")
    priority_areas: list[str] = Field(description="优先资助领域/方向 Priority areas")
    eligibility: list[str] = Field(description="申请资格 Eligibility requirements")
    required_sections: list[str] = Field(description="申报书要求的章节 Required sections")
    length_limits: str = Field(description="字数或篇幅限制 Word or page limits")
    duration: str = Field(description="项目执行期限 Project duration")
    budget_cap: str = Field(description="资助强度/经费上限 Budget cap")
    evaluation_criteria: list[str] = Field(description="评审标准 Evaluation criteria")
    deadlines: str = Field(description="申报截止时间 Deadlines")


SUMMARY_LABELS = {
    "programme_name": "项目名称",
    "funding_goals": "资助目标",
    "priority_areas": "优先资助领域",
    "eligibility": "申请资格",
    "required_sections": "申报书章节要求",
    "length_limits": "篇幅限制",
    "duration": "项目执行期限",
    "budget_cap": "资助上限",
    "evaluation_criteria": "评审标准",
    "deadlines": "截止时间",
}

MISSING = {"", "未说明", "not specified", "n/a", "none"}

# {language} and {guideline_text} are LangChain template variables.
ANALYSE_TEMPLATE = ChatPromptTemplate.from_messages([("human", ANALYSE_PROMPT)])


def split_text(text: str, size: int) -> list[str]:
    """Split on paragraph boundaries into pieces of at most `size` characters."""
    chunks, current = [], ""
    for para in text.split("\n"):
        while len(para) > size:            # a single huge paragraph
            chunks.append(para[:size])
            para = para[size:]
        if len(current) + len(para) + 1 > size and current:
            chunks.append(current)
            current = ""
        current += para + "\n"
    if current.strip():
        chunks.append(current)
    return chunks


def merge_summaries(parts: list[dict]) -> dict:
    """Combine chunk summaries: union of lists, distinct non-empty strings joined."""
    merged = {}
    for field in SUMMARY_LABELS:
        values = [p.get(field) for p in parts]
        if field in ("priority_areas", "eligibility", "required_sections", "evaluation_criteria"):
            seen = []
            for items in values:
                for item in items or []:
                    if item.strip().lower() not in MISSING and item not in seen:
                        seen.append(item)
            merged[field] = seen
        else:
            found = []
            for v in values:
                if v and v.strip().lower() not in MISSING and v not in found:
                    found.append(v)
            merged[field] = "；".join(found) if found else "未说明"
    return merged


def analyse_guideline(text: str, model: str = DEFAULT_MODEL, language: str = "中文",
                      on_progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Extract a structured summary. Long guidelines are read chunk by chunk
    (to stay under the per-request token limit) and the results are merged."""
    llm = get_llm(model, 0.1, ANALYSE_MAX_TOKENS)
    chain = ANALYSE_TEMPLATE | llm.with_structured_output(
        GuidelineSummary, method="json_schema", strict=True)

    room = TOKEN_LIMIT - ANALYSE_MAX_TOKENS - SAFETY_TOKENS
    chunks = split_text(text, _chars_for(room) - len(ANALYSE_PROMPT))
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress(i, len(chunks))
        result = chain.invoke({"language": language, "guideline_text": chunk})
        parts.append(result.model_dump())
    return parts[0] if len(parts) == 1 else merge_summaries(parts)


def format_summary(summary: dict) -> str:
    """Render the summary dict as readable text for the prompts."""
    lines = []
    for key, label in SUMMARY_LABELS.items():
        value = summary.get(key, "")
        if isinstance(value, list):
            value = "；".join(value) if value else "未说明"
        lines.append(f"- {label}：{value}")
    return "\n".join(lines)


# ---------------------------------------------------------------- sections

# The section prompt is passed in as a value, not parsed as a template, so a
# user can type { or } in an edited prompt without breaking it.
SECTION_TEMPLATE = ChatPromptTemplate.from_messages([
    ("system", "{system}"),
    ("human", "{prompt}"),
])


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "……（后略）"


def build_context(summary: dict, idea_title: str, idea_text: str, language: str,
                  sections: dict, upto: str, prompt: str = "") -> dict:
    """Context for one section: summary, idea, and every earlier section in SECTION_ORDER.

    Earlier sections share whatever room is left under the token limit, so each
    one is clipped to an equal share (the start of a section carries its key points).
    """
    context = {
        "guideline_summary": format_summary(summary),
        "project_idea": f"题目：{idea_title}\n{idea_text}".strip(),
        "language": language,
    }
    previous = []
    for key in SECTION_ORDER:
        if key == upto:
            break
        body = (sections.get(key) or "").strip()
        if body:
            previous.append((SECTIONS[key]["title"], body))

    used = len(SYSTEM_PROMPT) + len(prompt or SECTIONS[upto]["prompt"]) + \
        sum(len(v) for v in context.values())
    room = _chars_for(TOKEN_LIMIT - SECTION_MAX_TOKENS - SAFETY_TOKENS) - used
    share = max(200, room // len(previous)) if previous else 0
    context["previous_sections"] = "\n\n".join(
        f"## {title}\n{_clip(body, share)}" for title, body in previous
    ) or "（尚无已完成章节）"
    return context


def fill_prompt(template: str, context: dict) -> str:
    """Literal placeholder replacement, so stray braces in user edits are harmless."""
    for name, value in context.items():
        template = template.replace("{" + name + "}", value)
    return template


def generate_section(key: str, prompt: str, context: dict, model: str = DEFAULT_MODEL,
                     temperature: float = 0.7,
                     on_text: Optional[Callable[[str], None]] = None) -> str:
    """Generate one section. `on_text` receives the growing text while streaming."""
    chain = SECTION_TEMPLATE | get_llm(model, temperature, SECTION_MAX_TOKENS)
    text, finish = "", None
    for chunk in chain.stream({"system": SYSTEM_PROMPT,
                               "prompt": fill_prompt(prompt, context)}):
        if chunk.content:
            text += chunk.content
            if on_text:
                on_text(text)
        finish = chunk.response_metadata.get("finish_reason") or finish
    if finish == "length":
        text += "\n\n[输出达到长度上限，请重新生成或精简提示词]"
    return text.strip()


# ---------------------------------------------------------------- budget check

_NUMBER = r"(\d+(?:\.\d+)?)"


def _amount(cell: str) -> Optional[float]:
    match = re.search(_NUMBER, cell.replace(",", ""))
    return float(match.group(1)) if match else None


def _last_number(text: str) -> Optional[float]:
    numbers = re.findall(_NUMBER, text)
    return float(numbers[-1]) if numbers else None


def _fmt(value: float) -> str:
    return f"{round(value, 4):g}"


def is_table_row(line: str) -> bool:
    """Markdown table rows, with or without the leading and trailing pipes."""
    return line.count("|") >= 2


def _parse_item(item: str):
    """'名称：2 人 × 12 个月 × 0.30 万元 = 7.2 万元）' ->
    (label, factors, written subtotal, text after the subtotal such as '）')."""
    item = re.sub(r"(?<=\d),(?=\d{3})", "", item.strip())   # 30,000 -> 30000
    if "=" not in item:
        return item, [], None, ""
    left, right = item.rsplit("=", 1)
    factors = [_last_number(f) for f in re.split(r"[×*]", left)]
    factors = factors if len(factors) >= 2 and None not in factors else []
    tail = re.sub(r"^\s*\d+(?:\.\d+)?\s*(万元)?", "", right)
    return left.strip(), factors, _amount(right), tail.strip()


def _parse_budget(text: str):
    """Find the budget table. Returns (categories, total, first_line, last_line) or None."""
    lines = text.splitlines()
    idx = [i for i, line in enumerate(lines) if is_table_row(line)]
    if len(idx) < 2:
        return None
    categories, total = [], None
    for i in idx:
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if len(cells) < 2 or re.fullmatch(r"[:\- ]+", cells[0] + cells[1]):
            continue
        name, amount = cells[0].strip("* "), _amount(cells[1])
        if amount is None:                     # header row
            continue
        if "合计" in name or "总计" in name:
            total = amount
            continue
        basis = cells[2] if len(cells) > 2 else ""
        items = [_parse_item(p) for p in re.split(r"<br\s*/?>|；", basis) if p.strip()]
        categories.append({"name": name, "amount": amount, "items": items})
    return categories, total, idx[0], idx[-1]


def fix_budget(text: str) -> tuple[str, list[str]]:
    """Recalculate the budget in code: subtotal = product of factors, category =
    sum of subtotals, total = sum of categories. Returns (new text, corrections)."""
    parsed = _parse_budget(text)
    if not parsed:
        return text, []
    categories, total, first, last = parsed
    notes, rows = [], []
    for cat in categories:
        parts, subtotal_sum, has_subtotals = [], 0.0, False
        for label, factors, written, tail in cat["items"]:
            if factors:
                value = 1.0
                for f in factors:
                    value *= f
                if written is not None and abs(value - written) > 0.005:
                    item_name = re.split(r"[：:（(]", label)[0][:20]
                    notes.append(f"{cat['name']}·{item_name} 小计 {_fmt(written)} → {_fmt(value)} 万元")
            else:
                value = written
            if value is None:
                parts.append(label)
                continue
            has_subtotals = True
            subtotal_sum += value
            parts.append(f"{label} = {_fmt(value)}万元{tail}")
        amount = subtotal_sum if has_subtotals else cat["amount"]
        if abs(amount - cat["amount"]) > 0.005:
            notes.append(f"{cat['name']} {_fmt(cat['amount'])} → {_fmt(amount)} 万元")
        cat["amount"] = amount
        rows.append(f"| {cat['name']} | {_fmt(amount)} | {'<br>'.join(parts)} |")
    new_total = sum(c["amount"] for c in categories)
    if total is None or abs(new_total - total) > 0.005:
        notes.append(f"合计 {_fmt(total) if total is not None else '（缺失）'} → {_fmt(new_total)} 万元")
    table = ["| 预算科目 | 金额（万元） | 测算依据 |", "|---|---|---|", *rows,
             f"| **合计** | **{_fmt(new_total)}** | |"]
    lines = text.splitlines()
    return "\n".join(lines[:first] + table + lines[last + 1:]), notes


def check_budget(text: str, budget_cap: str = "") -> list[str]:
    """Problems code cannot fix by itself: missing table, wrong categories, over the cap.
    Run fix_budget first so the arithmetic is already correct."""
    parsed = _parse_budget(text)
    if not parsed:
        return ["未找到预算表格（应为 预算科目 | 金额（万元） | 测算依据 的 Markdown 表格）。"]
    categories, total, _, _ = parsed
    issues = [f"“{c['name']}”不应列入申请预算（间接费用由基金委核定）。"
              for c in categories if "间接" in c["name"]]
    category_sum = sum(c["amount"] for c in categories)
    if total is None or abs(category_sum - total) > 0.005:
        issues.append(f"各科目之和为 {_fmt(category_sum)} 万元，与合计不一致（可点击“自动修正计算”）。")
    caps = [float(n) for n in re.findall(_NUMBER + r"\s*万元", budget_cap)]
    if caps and category_sum > max(caps) + 0.005:
        issues.append(f"预算合计 {_fmt(category_sum)} 万元超过指南上限 {_fmt(max(caps))} 万元，"
                      f"请削减 {_fmt(category_sum - max(caps))} 万元。")
    return issues


# ---------------------------------------------------------------- full proposal

MAX_BUDGET_RETRIES = 2


def write_budget(prompt: str, context: dict, summary: dict, model: str, temperature: float,
                 on_text: Optional[Callable[[str], None]] = None) -> str:
    """Generate the budget, let code fix the arithmetic, and retry (up to twice)
    with the remaining problems, e.g. a total above the guideline's cap."""
    text = ""
    for _ in range(1 + MAX_BUDGET_RETRIES):
        text = generate_section("budget", prompt, context, model=model,
                                temperature=temperature, on_text=on_text)
        text, _ = fix_budget(text)
        issues = check_budget(text, summary.get("budget_cap", ""))
        if not issues:
            break
        prompt += ("\n\n【上一版预算未通过核算，请修正以下问题后重写完整预算】\n- " +
                   "\n- ".join(issues))
    return text


def generate_all(summary: dict, idea_title: str, idea_text: str, prompts: dict,
                 language: str = "中文", model: str = DEFAULT_MODEL, temperature: float = 0.7,
                 sections: Optional[dict] = None,
                 on_section: Optional[Callable[[str, str], None]] = None) -> dict:
    """Generate every section in SECTION_ORDER; each sees the ones written before it."""
    sections = dict(sections or {})
    for key in SECTION_ORDER:
        prompt = prompts.get(key, SECTIONS[key]["prompt"])
        context = build_context(summary, idea_title, idea_text, language, sections, key, prompt)
        if key == "budget":
            sections[key] = write_budget(prompt, context, summary, model, temperature)
        else:
            sections[key] = generate_section(key, prompt, context, model=model,
                                             temperature=temperature)
        if on_section:
            on_section(key, sections[key])
    return sections
