from __future__ import annotations

import json
import streamlit as st

from novel_memory_agent.agent import BudgetExceededError, NovelAgent
from novel_memory_agent.config import Settings
from novel_memory_agent.database import NovelDatabase
from novel_memory_agent.deepseek import DeepSeekError, DeepSeekClient
from novel_memory_agent.pricing import estimate_cny
from novel_memory_agent.ui import apply_app_style, render_hero, render_pills, render_topbar


st.set_page_config(
    page_title="NovelMemory Agent",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_app_style()


@st.cache_resource
def get_database(path: str) -> NovelDatabase:
    return NovelDatabase(path)


def read_uploaded_text(uploaded) -> str:
    raw = uploaded.getvalue()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请将文件保存为 UTF-8 后重试")


def build_runtime(db_path: str, api_key: str) -> tuple[NovelDatabase, Settings, NovelAgent]:
    database = get_database(db_path)
    settings = Settings.from_env(db_path)
    if api_key:
        settings.api_key = api_key
    client = DeepSeekClient(settings)
    return database, settings, NovelAgent(database, settings, client)


with st.sidebar:
    st.markdown("### NovelMemory")
    st.caption("本地小说记忆工作台")
    st.divider()
    st.markdown("#### DeepSeek 连接")
    db_path = st.text_input("SQLite 数据库", value="data/novel_memory.db")
    api_key = st.text_input(
        "DeepSeek API Key",
        type="password",
        placeholder="sk-...",
        help="密钥仅保存在当前会话，不写入代码或数据库。也可使用 DEEPSEEK_API_KEY 环境变量。",
    )
    database, settings, agent = build_runtime(db_path, api_key)
    novels = database.list_novels()
    novel_options = {f"{item['title']}（#{item['id']}）": item["id"] for item in novels}
    selected_label = st.selectbox("当前小说", list(novel_options), index=0) if novels else None
    novel_id = novel_options[selected_label] if selected_label else None
    if st.button("测试真实 API 连接", use_container_width=True):
        try:
            with st.spinner("正在发送极小测试请求……"):
                response = agent.client.test_connection(model=settings.default_model)
            test_cost = estimate_cny(
                response.model,
                response.usage,
                exchange_rate=settings.exchange_rate_cny_per_usd,
                period=settings.pricing_period,
            )
            if novel_id:
                database.log_usage(
                    novel_id=novel_id,
                    draft_id=None,
                    task_type="connection_test",
                    model=response.model,
                    prompt_tokens=response.usage.prompt_tokens,
                    cache_hit_tokens=response.usage.cache_hit_tokens,
                    cache_miss_tokens=response.usage.cache_miss_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    cost_cny=test_cost,
                )
            st.session_state["api_connection"] = {
                "ok": True,
                "model": response.model,
                "reply": response.content,
                "cost": test_cost,
            }
        except Exception as error:
            st.session_state["api_connection"] = {"ok": False, "error": str(error)}

    connection = st.session_state.get("api_connection")
    if connection and connection.get("ok"):
        st.success(f"已连接 {connection['model']}")
        st.caption(f"测试回复：{connection['reply']}｜估算费用 ¥{connection['cost']:.6f}")
    elif connection:
        st.error(connection.get("error", "连接失败"))
    elif settings.api_key:
        st.info("已读取密钥，点击上方按钮验证连接。")
    else:
        st.warning("请粘贴 API Key 或设置环境变量。")
    st.caption(f"接口：api.deepseek.com")
    st.caption(f"默认模型：{settings.default_model}")

api_connected = bool(st.session_state.get("api_connection", {}).get("ok"))
render_topbar(api_connected)
render_hero()

with st.container(border=True):
    st.markdown("#### 给下一章补充一句要求")
    hero_instruction = st.text_area(
        "创作要求",
        value=st.session_state.get("chapter_instruction_seed", ""),
        placeholder="例如：这一章更克制一点，暂时不要揭示周明的真实身份……",
        height=110,
        label_visibility="collapsed",
        key="hero_instruction",
    )
    left, middle, right = st.columns([2, 2, 1])
    left.caption("大纲决定方向，AI 负责扩写")
    middle.caption(f"模型：{settings.default_model}")
    if right.button("带入创作台 →", type="primary", use_container_width=True):
        st.session_state["chapter_instruction_seed"] = hero_instruction
        st.success("已保存。请打开下方“章节创作”标签。")

render_pills()

if novel_id:
    novel_metrics = database.get_novel(novel_id)
    chapter_count = len(database.list_chapters(novel_id))
    confirmed_memories = len(database.list_memories(novel_id, statuses=("confirmed",)))
    spend = float(database.usage_summary(novel_id)["cost_cny"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("当前作品", novel_metrics["title"])
    m2.metric("正文章节", chapter_count)
    m3.metric("已确认记忆", confirmed_memories)
    m4.metric("累计 API 成本", f"¥{spend:.4f}")

tabs = st.tabs(["项目与导入", "长期记忆", "章节创作", "成本与草稿", "产品说明"])

with tabs[0]:
    st.subheader("创建小说项目")
    with st.form("create_novel"):
        col1, col2 = st.columns(2)
        title = col1.text_input("小说名称")
        author = col2.text_input("作者（可选）")
        genre = col1.text_input("题材（可选）")
        target_chars = col2.number_input("默认每章字数", 500, 10000, 3000, 100)
        style_guide = st.text_area("叙事视角、文风和固定创作规则（可选）")
        budget = st.number_input("项目预算停止线（元）", 1.0, 200.0, 150.0, 1.0)
        submitted = st.form_submit_button("创建项目", type="primary")
        if submitted:
            if not title.strip():
                st.error("请填写小说名称")
            else:
                new_id = database.create_novel(
                    title,
                    author=author,
                    genre=genre,
                    style_guide=style_guide,
                    target_chapter_chars=int(target_chars),
                    budget_cny=float(budget),
                )
                st.success(f"项目已创建，编号 #{new_id}。请刷新页面并在左侧选择。")

    st.divider()
    if not novel_id:
        st.info("请先创建并选择一个小说项目。")
    else:
        novel = database.get_novel(novel_id)
        st.subheader(f"导入：{novel['title']}")
        manuscript_file = st.file_uploader("正文文件（TXT 或 Markdown）", type=["txt", "md"])
        manuscript_text = st.text_area("或粘贴正文", height=160, key="manuscript_text")
        if st.button("解析并替换正文", disabled=not (manuscript_file or manuscript_text)):
            try:
                text = read_uploaded_text(manuscript_file) if manuscript_file else manuscript_text
                count = agent.import_manuscript(novel_id, text)
                st.success(f"已导入 {count} 个正文章节。")
            except Exception as error:
                st.error(str(error))

        outline_file = st.file_uploader("大纲文件（TXT 或 Markdown）", type=["txt", "md"])
        outline_text = st.text_area("或粘贴大纲", height=160, key="outline_text")
        if st.button("解析并替换大纲", disabled=not (outline_file or outline_text)):
            try:
                text = read_uploaded_text(outline_file) if outline_file else outline_text
                count = agent.import_outline(novel_id, text)
                st.success(f"已导入 {count} 个大纲章节。")
            except Exception as error:
                st.error(str(error))

        chapters = database.list_chapters(novel_id)
        outline = database.list_outline(novel_id)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**正文章节：{len(chapters)}**")
            st.dataframe(
                [{"序号": row["ordinal"], "标题": row["title"], "摘要": row["summary"]} for row in chapters],
                use_container_width=True,
                hide_index=True,
            )
        with c2:
            st.markdown(f"**大纲章节：{len(outline)}**")
            st.dataframe(
                [
                    {
                        "序号": row["ordinal"],
                        "标题": row["title"],
                        "核心事件": row["core_event"],
                        "状态": row["status"],
                    }
                    for row in outline
                ],
                use_container_width=True,
                hide_index=True,
            )

with tabs[1]:
    if not novel_id:
        st.info("请先选择小说项目。")
    else:
        st.subheader("从正文提取候选记忆")
        st.warning("提取结果默认进入待确认区，不会直接成为正式事实。")
        chapters = database.list_chapters(novel_id)
        chapter_map = {f"{row['ordinal']}. {row['title']}": row["id"] for row in chapters}
        if chapter_map:
            chapter_label = st.selectbox("选择章节", list(chapter_map), key="memory_chapter")
            if st.button("分析本章并提取候选记忆"):
                try:
                    with st.spinner("DeepSeek 正在提取事实……"):
                        result = agent.analyze_chapter(novel_id, chapter_map[chapter_label])
                    st.success(
                        f"摘要已更新，新增 {result['memory_count']} 条候选记忆。"
                    )
                except (DeepSeekError, BudgetExceededError, Exception) as error:
                    st.error(str(error))
        else:
            st.info("请先导入正文。")

        st.divider()
        statuses = st.multiselect(
            "显示状态", ["candidate", "confirmed", "rejected"], default=["candidate", "confirmed"]
        )
        memories = database.list_memories(
            novel_id, statuses=tuple(statuses) if statuses else ("candidate", "confirmed")
        )
        st.markdown(f"**记忆数量：{len(memories)}**")
        for memory in memories:
            badge = "📌 " if memory["pinned"] else ""
            with st.expander(
                f"{badge}[{memory['status']}] [{memory['kind']}] {memory['subject']}"
            ):
                st.write(memory["content"])
                if memory["evidence"]:
                    st.caption(f"证据：{memory['evidence']}")
                st.caption(
                    f"来源：{memory.get('source_chapter_title') or memory['source_type']}；"
                    f"置信度：{memory['confidence']:.2f}"
                )
                c1, c2 = st.columns(2)
                if c1.button("确认为正式记忆", key=f"confirm_{memory['id']}"):
                    database.update_memory_status(memory["id"], "confirmed")
                    st.rerun()
                if c2.button("废弃", key=f"reject_{memory['id']}"):
                    database.update_memory_status(memory["id"], "rejected")
                    st.rerun()

with tabs[2]:
    if not novel_id:
        st.info("请先选择小说项目。")
    else:
        outline = [row for row in database.list_outline(novel_id) if row["status"] != "written"]
        outline_map = {
            f"{row['ordinal']}. {row['title']}｜{row['core_event']}": row["id"] for row in outline
        }
        if not outline_map:
            st.info("请先导入大纲，或所有大纲章节已经完成。")
        else:
            selected_outline_label = st.selectbox("待写章节", list(outline_map))
            selected_outline_id = outline_map[selected_outline_label]
            instruction = st.text_area(
                "作者临时要求（可留空）",
                value=st.session_state.get("chapter_instruction_seed", ""),
                placeholder="例如：这一章写得压抑一点，暂时不要揭示周明的身份。",
                key="chapter_instruction",
            )
            novel = database.get_novel(novel_id)
            target_chars = st.number_input(
                "目标字数", 500, 10000, int(novel["target_chapter_chars"]), 100
            )
            col1, col2 = st.columns(2)
            if col1.button("预览最小充分上下文"):
                try:
                    bundle = agent.preview_context(novel_id, selected_outline_id, instruction)
                    st.session_state["context_preview"] = bundle.text
                    st.session_state["context_tokens"] = bundle.estimated_tokens
                except Exception as error:
                    st.error(str(error))
            if col2.button("生成章节并检查", type="primary"):
                try:
                    with st.spinner("正在规划、扩写并检查连续性……"):
                        result = agent.generate_chapter(
                            novel_id,
                            selected_outline_id,
                            instruction=instruction,
                            target_chars=int(target_chars),
                        )
                    st.session_state["last_result"] = result
                except (DeepSeekError, BudgetExceededError, Exception) as error:
                    st.error(str(error))

            if "context_preview" in st.session_state:
                st.caption(f"估算上下文：{st.session_state.get('context_tokens', 0):,} Token")
                st.text_area(
                    "即将发送的上下文包",
                    st.session_state["context_preview"],
                    height=320,
                    disabled=True,
                )

            result = st.session_state.get("last_result")
            if result:
                st.subheader("章节任务卡")
                st.json(result.task_card, expanded=True)
                st.subheader("章节草稿")
                edited_draft = st.text_area(
                    "正文", result.draft, height=500, key=f"generated_draft_{result.draft_id}"
                )
                st.subheader("一致性检查")
                st.json(result.continuity_report, expanded=True)
                if st.button("确认章节并提取新增候选记忆", type="primary"):
                    try:
                        with st.spinner("正在保存章节并提取增量记忆……"):
                            database.update_draft_content(result.draft_id, edited_draft)
                            saved = agent.accept_and_extract_memories(result.draft_id)
                        st.success(
                            f"章节已确认，新增 {saved['candidate_memories']} 条待确认记忆。"
                        )
                        st.session_state.pop("last_result", None)
                    except (DeepSeekError, BudgetExceededError, Exception) as error:
                        st.error(str(error))

with tabs[3]:
    if not novel_id:
        st.info("请先选择小说项目。")
    else:
        summary = database.usage_summary(novel_id)
        novel = database.get_novel(novel_id)
        cols = st.columns(4)
        cols[0].metric("API 调用", int(summary["calls"]))
        cols[1].metric("输入 Token", f"{int(summary['prompt_tokens']):,}")
        cols[2].metric("输出 Token", f"{int(summary['completion_tokens']):,}")
        cols[3].metric(
            "累计估算费用",
            f"¥{float(summary['cost_cny']):.4f}",
            help=f"项目停止线：¥{float(novel['budget_cny']):.2f}",
        )
        usage = database.list_usage(novel_id)
        st.dataframe(usage, use_container_width=True, hide_index=True)

        st.subheader("历史草稿")
        for draft in database.list_drafts(novel_id):
            with st.expander(f"#{draft['id']} {draft['title']}｜{draft['status']}"):
                st.text_area(
                    "正文",
                    draft["content"],
                    height=300,
                    key=f"draft_text_{draft['id']}",
                    disabled=True,
                )
                try:
                    st.json(json.loads(draft["continuity_json"]))
                except json.JSONDecodeError:
                    st.code(draft["continuity_json"])

with tabs[4]:
    st.markdown(
        """
### v0.1 核心目标

在不重复发送全部前文的情况下，利用结构化长期记忆和相关原文检索，为每一章组装“最小充分上下文”。

### 事实安全边界

- AI 提取的信息先进入候选区；
- 只有作者确认的信息才参与后续检索；
- 新章节只有经作者确认后才进入正式正文；
- 一致性检查默认只报告问题，不自动覆盖正文；
- 小说正文保存在本地，只有当前任务需要的上下文会发送给 DeepSeek。
        """
    )
