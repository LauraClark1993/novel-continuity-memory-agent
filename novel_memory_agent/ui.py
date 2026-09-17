from __future__ import annotations

import streamlit as st


APP_CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700&display=swap');

:root {
  --ink: #191a1d;
  --muted: #6f7178;
  --line: rgba(25, 26, 29, 0.10);
  --paper: rgba(255, 255, 255, 0.84);
  --accent: #202124;
}

html, body, [class*="css"] {
  font-family: "DM Sans", "Noto Sans SC", sans-serif;
}

.stApp {
  color: var(--ink);
  background:
    radial-gradient(circle at 46% 29%, rgba(255, 230, 120, 0.30), transparent 18%),
    radial-gradient(circle at 60% 34%, rgba(255, 190, 190, 0.22), transparent 22%),
    radial-gradient(circle at 44% 49%, rgba(198, 221, 255, 0.25), transparent 24%),
    radial-gradient(circle at 60% 58%, rgba(229, 199, 255, 0.20), transparent 22%),
    #fbfbfa;
  background-attachment: fixed;
}

header[data-testid="stHeader"] {
  background: transparent;
  height: 0;
  min-height: 0;
}

[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] {
  display: none !important;
}

.block-container {
  max-width: 1180px;
  padding-top: 1.15rem;
  padding-bottom: 4rem;
}

.nm-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.2rem 0 1rem;
}

.nm-brand {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.nm-logo {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: inline-grid;
  place-items: center;
  background: #1d1e21;
  color: #fff;
  box-shadow: 0 6px 18px rgba(29, 30, 33, 0.16);
  font-size: 15px;
}

.nm-topmeta {
  color: var(--muted);
  font-size: 0.82rem;
  padding: 0.42rem 0.7rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(255,255,255,0.7);
}

.nm-hero {
  text-align: center;
  padding: 4.2rem 1rem 1.35rem;
}

.nm-eyebrow {
  display: inline-flex;
  padding: 0.36rem 0.72rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--muted);
  background: rgba(255,255,255,0.64);
  font-size: 0.78rem;
  margin-bottom: 1rem;
}

.nm-hero h1 {
  font-size: clamp(2rem, 4vw, 3.25rem);
  line-height: 1.08;
  letter-spacing: -0.045em;
  margin: 0;
  color: #17181b;
}

.nm-hero p {
  max-width: 620px;
  margin: 0.9rem auto 0;
  color: var(--muted);
  line-height: 1.75;
}

.nm-status {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  color: #4e5056;
  font-size: 0.82rem;
}

.nm-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22a06b;
  box-shadow: 0 0 0 4px rgba(34,160,107,0.11);
}

.nm-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.55rem;
  margin: 0.8rem 0 2.7rem;
}

.nm-pill {
  color: #606269;
  background: rgba(255,255,255,0.58);
  border: 1px solid rgba(25,26,29,0.08);
  border-radius: 999px;
  padding: 0.42rem 0.72rem;
  font-size: 0.78rem;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
  background: rgba(255,255,255,0.82);
  border: 1px solid rgba(25,26,29,0.10);
  border-radius: 18px;
  box-shadow: 0 18px 50px rgba(28,29,33,0.08);
  backdrop-filter: blur(18px);
}

div[data-testid="stTextArea"] textarea,
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-baseweb="select"] > div {
  background: rgba(255,255,255,0.78) !important;
  border-color: rgba(25,26,29,0.12) !important;
  border-radius: 12px !important;
}

.stButton > button, .stFormSubmitButton > button {
  border-radius: 999px;
  border: 1px solid rgba(25,26,29,0.12);
  min-height: 2.45rem;
  font-weight: 600;
  transition: transform .15s ease, box-shadow .15s ease;
}

.stButton > button:hover, .stFormSubmitButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgba(28,29,33,0.10);
}

.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: #1c1d20;
  color: #fff;
}

div[data-testid="stMetric"] {
  background: rgba(255,255,255,0.68);
  border: 1px solid rgba(25,26,29,0.08);
  padding: 0.85rem 1rem;
  border-radius: 14px;
}

.stTabs [data-baseweb="tab-list"] {
  gap: 0.4rem;
  background: rgba(255,255,255,0.56);
  border: 1px solid rgba(25,26,29,0.08);
  border-radius: 14px;
  padding: 0.32rem;
}

.stTabs [data-baseweb="tab"] {
  height: 2.6rem;
  border-radius: 10px;
  padding: 0 1rem;
}

.stTabs [aria-selected="true"] {
  background: #fff;
  box-shadow: 0 3px 12px rgba(28,29,33,0.08);
}

section[data-testid="stSidebar"] {
  background: rgba(248,248,247,0.94);
  border-right: 1px solid rgba(25,26,29,0.08);
}

@media (max-width: 720px) {
  .nm-hero { padding-top: 2.2rem; }
  .nm-topmeta { display: none; }
  .block-container { padding-left: 1rem; padding-right: 1rem; }
}
</style>
"""


def apply_app_style() -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)


def render_topbar(api_connected: bool) -> None:
    state = "DeepSeek 已连接" if api_connected else "DeepSeek 待连接"
    dot = '<span class="nm-dot"></span>' if api_connected else ""
    st.markdown(
        f"""
        <div class="nm-topbar">
          <div class="nm-brand"><span class="nm-logo">N</span> NovelMemory</div>
          <div class="nm-topmeta"><span class="nm-status">{dot}{state}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    st.markdown(
        """
        <section class="nm-hero">
          <div class="nm-eyebrow">LONG-FORM FICTION MEMORY AGENT</div>
          <h1>今天想把故事写到哪里？</h1>
          <p>把完整正文留在本地，只向模型发送这一章真正需要的记忆、前情和伏笔。</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_pills() -> None:
    st.markdown(
        """
        <div class="nm-pills">
          <span class="nm-pill">✦ 生成章节任务卡</span>
          <span class="nm-pill">⌁ 召回历史伏笔</span>
          <span class="nm-pill">✓ 检查人物一致性</span>
          <span class="nm-pill">¥ 追踪 Token 成本</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
