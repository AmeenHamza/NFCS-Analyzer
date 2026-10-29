"""LLM logic: read a guideline, summarise it, and generate proposal sections (Groq)."""

import io
import json
import os
from pathlib import Path
from typing import Callable, Optional

import docx
import groq
from dotenv import load_dotenv
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

_client: Optional[groq.Groq] = None


def get_client() -> groq.Groq:
    """Create the client lazily so the UI can start before a key is set.

    max_retries lets the SDK wait out per-minute rate limits (it honours retry-after).
    """
    global _client
    if _client is None:
        _client = groq.Groq(max_retries=8)  # reads GROQ_API_KEY from env / .env
    return _client


def has_api_key() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _model_options(model: str) -> dict:
    """Keep reasoning short so the token budget goes to the answer."""
    if model.startswith("qwen/"):
        return {"reasoning_format": "hidden", "reasoning_effort": "none"}
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low"}
    return {}


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


def _analyse_chunk(chunk: str, model: str, language: str) -> dict:
    response = get_client().chat.completions.create(
        model=model,
        max_tokens=ANALYSE_MAX_TOKENS,
        temperature=0.1,
        messages=[{
            "role": "user",
            "content": ANALYSE_PROMPT.replace("{language}", language)
                                     .replace("{guideline_text}", chunk),
        }],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "guideline_summary", "strict": True,
                            "schema": GuidelineSummary.model_json_schema()},
        },
        **_model_options(model),
    )
    content = response.choices[0].message.content or "{}"
    return GuidelineSummary.model_validate(json.loads(content)).model_dump()


def analyse_guideline(text: str, model: str = DEFAULT_MODEL, language: str = "中文",
                      on_progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Extract a structured summary. Long guidelines are read chunk by chunk
    (to stay under the per-request token limit) and the results are merged."""
    room = TOKEN_LIMIT - ANALYSE_MAX_TOKENS - SAFETY_TOKENS
    chunk_chars = _chars_for(room) - len(ANALYSE_PROMPT)
    chunks = split_text(text, chunk_chars)
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress(i, len(chunks))
        parts.append(_analyse_chunk(chunk, model, language))
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
    stream = get_client().chat.completions.create(
        model=model,
        max_tokens=SECTION_MAX_TOKENS,
        temperature=temperature,
        stream=True,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": fill_prompt(prompt, context)},
        ],
        **_model_options(model),
    )
    text, finish = "", None
    for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        if choice.delta.content:
            text += choice.delta.content
            if on_text:
                on_text(text)
        finish = choice.finish_reason or finish
    if finish == "length":
        text += "\n\n[输出达到长度上限，请重新生成或精简提示词]"
    return text.strip()


def generate_all(summary: dict, idea_title: str, idea_text: str, prompts: dict,
                 language: str = "中文", model: str = DEFAULT_MODEL, temperature: float = 0.7,
                 sections: Optional[dict] = None,
                 on_section: Optional[Callable[[str, str], None]] = None) -> dict:
    """Generate every section in SECTION_ORDER; each sees the ones written before it."""
    sections = dict(sections or {})
    for key in SECTION_ORDER:
        prompt = prompts.get(key, SECTIONS[key]["prompt"])
        context = build_context(summary, idea_title, idea_text, language, sections, key, prompt)
        sections[key] = generate_section(key, prompt, context, model=model,
                                         temperature=temperature)
        if on_section:
            on_section(key, sections[key])
    return sections
