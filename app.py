"""Streamlit interface for the proposal agent.  Run with:  streamlit run app.py"""

import groq
import streamlit as st

import agent
from export import to_docx
from prompts import EXAMPLE_IDEA_TEXT, EXAMPLE_IDEA_TITLE, SECTION_ORDER, SECTIONS

st.set_page_config(page_title="项目申报书智能体 Proposal Agent", page_icon="📝", layout="wide")

SUMMARY_FIELDS = list(agent.SUMMARY_LABELS)
LIST_FIELDS = {"priority_areas", "eligibility", "required_sections", "evaluation_criteria"}

# ------------------------------------------------------------------ state

ss = st.session_state
ss.setdefault("guideline_text", "")
ss.setdefault("summary", None)
ss.setdefault("idea_title", "")
ss.setdefault("idea_text", "")
for key in SECTION_ORDER:
    ss.setdefault(f"prompt_{key}", SECTIONS[key]["prompt"])
    ss.setdefault(f"out_{key}", "")

# Streamlit drops a widget's state when the widget isn't drawn in a run;
# re-assigning keeps prompts, outputs and summary edits alive across steps.
for k in list(ss.keys()):
    if str(k).startswith(("prompt_", "out_", "sum_")):
        ss[k] = ss[k]


def current_summary() -> dict:
    """The summary as edited by the user in step 1."""
    summary = {}
    for field in SUMMARY_FIELDS:
        value = ss.get(f"sum_{field}", "")
        if field in LIST_FIELDS:
            value = [line.strip() for line in value.splitlines() if line.strip()]
        summary[field] = value
    return summary


def set_summary(summary: dict) -> None:
    ss.summary = summary
    for field in SUMMARY_FIELDS:
        value = summary.get(field, "")
        ss[f"sum_{field}"] = "\n".join(value) if isinstance(value, list) else str(value)


def current_sections() -> dict:
    return {key: ss[f"out_{key}"] for key in SECTION_ORDER}


def reset_prompt(key: str) -> None:
    ss[f"prompt_{key}"] = SECTIONS[key]["prompt"]


def load_example() -> None:
    ss.idea_title = EXAMPLE_IDEA_TITLE
    ss.idea_text = EXAMPLE_IDEA_TEXT


def section_title(key: str, language: str) -> str:
    return SECTIONS[key]["title"] if language == "中文" else SECTIONS[key]["title_en"]


def show_api_error(err: Exception) -> None:
    if isinstance(err, groq.AuthenticationError):
        st.error("API key rejected. Check GROQ_API_KEY in your .env file.")
    elif isinstance(err, groq.RateLimitError):
        st.error("Groq rate limit reached (free tier: 8,000 tokens/minute). "
                 "Wait a minute and try again.")
    elif isinstance(err, groq.APIStatusError) and err.status_code == 413:
        st.error("Request too large for the free-tier limit. Shorten the prompt or the "
                 "project description, or lower GROQ_TOKEN_LIMIT in .env.")
    else:
        st.error(f"Generation failed: {err}")


# ------------------------------------------------------------------ sidebar

with st.sidebar:
    st.header("⚙️ 设置 Settings")
    model_label = st.selectbox("模型 Model", list(agent.MODELS))
    model = agent.MODELS[model_label]
    temperature = st.slider(
        "温度 Temperature", 0.0, 1.5, 0.7, 0.1,
        help="Lower = more focused and repeatable; higher = more varied wording.",
    )
    language = st.radio("输出语言 Language", ["中文", "English"], horizontal=True)
    st.divider()
    if agent.has_api_key():
        st.success("Groq API key loaded")
    else:
        st.warning("No GROQ_API_KEY found. Copy .env.example to .env and add your key.")
    st.caption("Groq free tier: 8,000 tokens/minute, so the app pauses between "
               "sections. Generating all 8 takes about 8–10 minutes.")
    done = sum(bool(ss[f"out_{k}"].strip()) for k in SECTION_ORDER)
    st.progress(done / len(SECTION_ORDER), text=f"已完成章节 {done}/{len(SECTION_ORDER)}")

st.title("📝 项目申报书智能体")
st.caption("上传项目申报指南 → 提取要点 → 输入项目设想 → 分章节编辑提示词并生成 → 导出 Word")

# ------------------------------------------------------------------ step 1

st.header("① 上传并解析项目指南 Guideline")
tab_upload, tab_paste = st.tabs(["上传文件 Upload", "粘贴文本 Paste"])
with tab_upload:
    uploaded = st.file_uploader("PDF / DOCX / TXT", type=["pdf", "docx", "txt", "md"])
with tab_paste:
    pasted = st.text_area("指南全文 Guideline text", height=200)

if st.button("🔍 解析指南 Analyse", type="primary"):
    try:
        text = agent.load_guideline(uploaded) if uploaded else pasted.strip()
        if not text:
            st.warning("请先上传文件或粘贴指南文本。")
        else:
            ss.guideline_text = text
            with st.spinner("正在阅读指南并提取要点…"):
                progress = st.empty()
                set_summary(agent.analyse_guideline(
                    text, model=model, language=language,
                    on_progress=lambda i, n: progress.caption(
                        f"正在阅读第 {i}/{n} 部分（长指南分段读取）" if n > 1 else "")))
                progress.empty()
    except groq.APIError as err:
        show_api_error(err)
    except ValueError as err:
        st.error(f"Could not read the guideline: {err}")

if ss.summary:
    st.success(f"已解析指南（{len(ss.guideline_text):,} 字符）。可直接修改下方要点，生成时将使用修改后的内容。")
    col_a, col_b = st.columns(2)
    for i, field in enumerate(SUMMARY_FIELDS):
        col = col_a if i % 2 == 0 else col_b
        label = agent.SUMMARY_LABELS[field]
        if field in LIST_FIELDS:
            col.text_area(f"{label}（每行一条）", key=f"sum_{field}", height=110)
        else:
            col.text_input(label, key=f"sum_{field}")
    with st.expander("查看指南原文 Raw guideline text"):
        st.text(ss.guideline_text[:20000])

# ------------------------------------------------------------------ step 2

st.header("② 项目设想 Project idea")
st.button("填入示例 Load example idea", on_click=load_example)
st.text_input("项目题目 Title", key="idea_title")
st.text_area("项目简介（几句话即可）Short description", key="idea_text", height=150)

ready = bool(ss.summary) and bool(ss.idea_title.strip())

# ------------------------------------------------------------------ step 3

st.header("③ 分章节生成 Sections")
if not ready:
    st.info("完成第①步解析和第②步项目题目后即可生成。")

if st.button("⚡ 按顺序生成全部章节 Generate all", disabled=not ready):
    summary = current_summary()
    prompts = {key: ss[f"prompt_{key}"] for key in SECTION_ORDER}
    with st.status("正在依次生成各章节…", expanded=True) as status:
        def on_section(key, text):
            ss[f"out_{key}"] = text
            st.write(f"✅ {section_title(key, language)}")
        try:
            agent.generate_all(summary, ss.idea_title, ss.idea_text, prompts,
                               language=language, model=model, temperature=temperature,
                               on_section=on_section)
            status.update(label="全部章节已生成", state="complete")
        except groq.APIError as err:
            status.update(label="生成中断（已完成的章节已保留）", state="error")
            show_api_error(err)

for key in SECTION_ORDER:
    has_text = bool(ss[f"out_{key}"].strip())
    with st.expander(f"{'✅' if has_text else '⬜'} {section_title(key, language)}"):
        st.text_area("提示词 Prompt (可编辑；占位符 {guideline_summary} {project_idea} "
                     "{previous_sections} {language})",
                     key=f"prompt_{key}", height=260)
        c1, c2, _ = st.columns([1, 1, 4])
        generate = c1.button("生成 / 重新生成", key=f"gen_{key}", disabled=not ready,
                             type="primary")
        c2.button("恢复默认提示词", key=f"reset_{key}", on_click=reset_prompt, args=(key,))

        if generate:
            # Only this section is rewritten; earlier sections are used as context.
            context = agent.build_context(current_summary(), ss.idea_title, ss.idea_text,
                                          language, current_sections(), key,
                                          ss[f"prompt_{key}"])
            live = st.empty()
            try:
                ss[f"out_{key}"] = agent.generate_section(
                    key, ss[f"prompt_{key}"], context, model=model, temperature=temperature,
                    on_text=lambda t: live.markdown(t + " ▌"))
                live.empty()
            except groq.APIError as err:
                live.empty()
                show_api_error(err)

        st.text_area("生成结果（可直接编辑）Output", key=f"out_{key}", height=360)

# ------------------------------------------------------------------ step 4

st.header("④ 导出 Export")
sections = [(section_title(k, language), ss[f"out_{k}"]) for k in SECTION_ORDER
            if ss[f"out_{k}"].strip()]
if sections:
    title = ss.idea_title.strip() or "项目申报书"
    programme = (ss.get("sum_programme_name") or "").strip()
    st.download_button(
        "📄 下载 Word (.docx)",
        data=to_docx(title, sections, subtitle=programme),
        file_name=f"{title[:40]}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary",
    )
    st.download_button(
        "下载 Markdown (.md)",
        data="\n\n".join([f"# {title}"] + [f"## {h}\n\n{b}" for h, b in sections]),
        file_name=f"{title[:40]}.md",
        mime="text/markdown",
    )
else:
    st.info("生成至少一个章节后即可导出。")
