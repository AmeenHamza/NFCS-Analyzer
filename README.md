# 项目申报书智能体 · Proposal Agent

> 已知项目申报指南，研发智能体，利用大模型生成项目申报书。
> Given a funding guideline, an agent that uses an LLM to write a project proposal.

## Problem

Writing a funding proposal (for example an NSFC application) means reading a long guideline, pulling out the rules that matter, and then writing eight interlocking sections that must agree with one another *and* with the guideline. This tool automates the first draft. The researcher keeps full control over every prompt and every paragraph.

## Features

- **Software interface** (Streamlit): upload, edit, generate and export, all in the browser.
- **Guideline analysis**: upload a PDF, DOCX or text file, or paste the text. The agent extracts a structured summary: programme, funding goals, priority areas, eligibility, required sections, length limits, duration, budget cap, evaluation criteria and deadlines. Every field can be edited before generating.
- **Per-section prompts (分章节设定提示词)**: each of the eight NSFC sections has its own prompt, which you can view, edit and reset to default in the UI.
- **Sequential, consistent generation**: sections are written in order. Each one sees the guideline summary, the project idea and every section written before it.
- **Edit and regenerate**: generated text can be edited in place. Regenerating one section rewrites only that section and leaves the others alone.
- **Export** to `.docx` (title page, numbered headings, bullet lists and tables, Chinese fonts), with Markdown as an extra option.
- **Language toggle** (中文 / English), **temperature** slider, and **model choice** on the free Groq API: GPT-OSS 120B (default) and GPT-OSS 20B (faster). Qwen3.8 27B is supported in code but not offered, because the free tier caps its output at 1,000 tokens per minute, which is less than one section.

Sections: 立项依据 · 研究目标 · 研究内容 · 研究方案与技术路线 · 创新点 · 进度安排 · 预期成果 · 经费预算

## Architecture

```
 ┌──────────────┐   load_guideline()   ┌───────────────┐  analyse_guideline()  ┌────────────────────┐
 │ Guideline    │ ───────────────────▶ │ Plain text    │ ────────────────────▶ │ Structured summary │
 │ PDF/DOCX/TXT │                      └───────────────┘   (JSON schema)       │ (editable in UI)   │
 └──────────────┘                                                              └─────────┬──────────┘
                                                                                         │
                        Project idea (title + description) ─────────────────────────────┤
                                                                                         ▼
     ┌──────────────────────────── generate_section(), in SECTION_ORDER ─────────────────────────────┐
     │ 立项依据 → 研究目标 → 研究内容 → 研究方案 → 创新点 → 进度安排 → 预期成果 → 经费预算               │
     │ each prompt = template(section) + summary + idea + all previous sections                     │
     └───────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                                     ▼
                                      to_docx()  →  proposal.docx
```

| File | Responsibility |
|---|---|
| `prompts.py` | `SECTIONS` (title + default prompt per section), `SECTION_ORDER`, shared `SYSTEM_PROMPT` with the guard rules, the guideline-analysis prompt and an example idea |
| `agent.py` | `load_guideline`, `analyse_guideline` (JSON-schema structured output, chunked for long guidelines), `build_context` (fits context into the token budget), `generate_section` (streaming), `generate_all` |
| `app.py` | Streamlit UI. All state is kept in `st.session_state` |
| `export.py` | `to_docx(title, sections) → bytes` |

## How to run

Requires Python 3.10+ and a free Groq API key from https://console.groq.com/keys.

```bash
git clone <repo-url> proposal-agent
cd proposal-agent
python -m venv venv
# Windows:  venv\Scripts\activate      macOS/Linux:  source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env
# edit .env and set GROQ_API_KEY
streamlit run app.py
```

The app opens at http://localhost:8501.

1. **① Upload** the guideline and click **解析指南**. Check and correct the summary, especially the duration and budget cap.
2. **② Enter** a project title and a short description, or click **填入示例** to load an example.
3. **③ Generate**: click **按顺序生成全部章节**, or open a section, edit its prompt and click **生成 / 重新生成**.
4. **④ Export**: click **下载 Word (.docx)**.

## Screenshots

| Upload & summary | Section prompts |
|---|---|
| ![](docs/1_upload_summary.png) | ![](docs/2_section_prompts.png) |
| **Generated output** | **Export** |
| ![](docs/3_generated_output.png) | ![](docs/4_export.png) |

## Design choices

- **Structured extraction first.** The guideline is reduced once to a schema-validated summary: a Pydantic model is sent as a strict JSON schema (`response_format={"type": "json_schema", ...}`) and the reply is validated against it. Every section then works from the same facts instead of re-reading a 30-page PDF. The summary can be edited, which lets a human fix a misread budget cap before it spreads into every section.
- **Built for a free API.** Groq's free tier allows 8,000 tokens per minute, and a single request can't be larger than that. So long guidelines are read in chunks and the partial summaries are merged in code; earlier sections are clipped to share whatever room is left in the context; and the client automatically waits and retries when the per-minute limit is hit. With a paid plan, set `GROQ_TOKEN_LIMIT` higher and everything scales up.
- **Sequential generation with accumulated context.** Writing in NSFC order and passing all earlier sections forward keeps terminology, objectives and the technical route consistent. The timeline and budget are written last, so they can match the research content.
- **Guard rules in the system prompt** (applied to every section) and repeated in the relevant section prompts:
  - no invented citations or statistics: the model writes `[待补充文献]` / `[待补充数据]` placeholders instead;
  - the budget total stays within the guideline's cap and must add up;
  - the timeline matches the project duration exactly;
  - every section must address the guideline's priority areas.
- **Literal placeholder filling** (not `str.format`). A user can type `{` or `}` in an edited prompt without crashing the app.
- **Reasoning kept short.** GPT-OSS runs at low reasoning effort (and Qwen's thinking mode is off if you add it back), so the limited token budget goes to the proposal text rather than hidden reasoning.
- **No invented names.** Besides citations and statistics, the rules forbid naming any dataset, benchmark, metric or model the model isn't certain exists. It must write `[待补充数据集]` or a generic description instead.
- **Streaming output**, so long sections appear as they are written.

## Limitations

- Scanned (image-only) PDFs have no extractable text. Run OCR first or paste the text instead.
- The output is a **first draft**. Citations, preliminary results, team information and exact budget figures must be filled in and checked by the applicant.
- The guideline summary is only as good as the guideline's wording. Always check the duration and budget cap.
- The technical-route *diagram* is not drawn. The methodology section describes the route in text, ready to turn into a figure.
- On the free tier, generating all eight sections takes about 8–10 minutes because of the per-minute token limit, and later sections see shortened versions of the earlier ones. A very long guideline (for example the whole NSFC 指南) is read in many chunks and can take several minutes, so upload only the part for your programme.
- No user accounts or saved projects: state lives in the browser session. Export to `.docx`/`.md` to keep your work.
