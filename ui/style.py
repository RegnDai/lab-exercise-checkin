"""全局样式：统一的蓝色设计 token，只注入一次。

原版有两套 CSS 重复注入且颜色到处硬编码；这里收敛为 CSS 变量，
以后调色只改 :root 一处。
"""
import streamlit as st

APP_CSS = """
<style>
:root {
    --ink: #172033;          /* 主文字 */
    --ink-soft: #475569;     /* 次级文字 */
    --ink-faint: #64748B;    /* 说明文字 */
    --blue: #2563EB;         /* 主色 */
    --blue-deep: #1D4ED8;    /* 深主色 */
    --blue-100: #DCEBFF;
    --blue-50: #EAF2FF;
    --blue-25: #F4F8FF;
    --line: #C8D8F0;         /* 边框 */
    --line-soft: #E5EEF8;    /* 行分隔 */
    --card-radius: 1.15rem;
    --shadow: 0 10px 24px rgba(37, 99, 235, 0.08);
    --shadow-hover: 0 14px 30px rgba(37, 99, 235, 0.11);
}

.block-container {
    max-width: 1120px;
    padding-top: 1.6rem;
    padding-bottom: 3rem;
}

h1, h2, h3 { letter-spacing: -0.03em; }
h1 { font-size: 1.85rem; margin-bottom: 0.35rem; }
h3 { margin-top: 1.2rem; }

[data-testid="stCaptionContainer"] { color: var(--ink-faint); }

/* 原生 metric 卡片 */
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, #FFFFFF 0%, var(--blue-50) 100%);
    border: 1px solid var(--line);
    border-radius: var(--card-radius);
    padding: 0.9rem 1.05rem;
    box-shadow: var(--shadow);
}
div[data-testid="stMetric"] label { color: var(--ink-soft) !important; font-weight: 650 !important; }
div[data-testid="stMetricValue"] {
    color: var(--ink) !important;
    font-weight: 800 !important;
    font-size: 1.55rem;
    line-height: 1.2;
    white-space: normal;
    word-break: keep-all;
}
div[data-testid="stMetricDelta"] { color: var(--blue) !important; }

/* 按钮 / 容器 */
.stButton > button,
[data-testid="stFormSubmitButton"] button {
    border-radius: 999px;
    padding: 0.55rem 1.2rem;
    border: 1px solid rgba(37, 99, 235, 0.18);
}
div[data-testid="stExpander"] {
    border-radius: 16px;
    border: 1px solid rgba(37, 99, 235, 0.12);
    overflow: hidden;
}
div[data-testid="stDataFrame"] { border-radius: 16px; overflow: hidden; }
hr { margin: 1.4rem 0; }

/* 自定义统计卡 */
.blue-stat-card {
    background:
        radial-gradient(circle at top right, rgba(37, 99, 235, 0.16), transparent 36%),
        linear-gradient(135deg, #FFFFFF 0%, var(--blue-50) 100%);
    border: 1px solid var(--line);
    border-radius: var(--card-radius);
    padding: 1rem 1.1rem;
    min-height: 112px;
    box-shadow: var(--shadow);
    display: flex;
    flex-direction: column;
    justify-content: center;
}
.blue-stat-card:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-hover);
    transition: all 0.16s ease;
}
.blue-stat-label { color: var(--ink-soft); font-size: 0.92rem; font-weight: 650; letter-spacing: 0.01em; margin-bottom: 0.45rem; }
.blue-stat-value { color: var(--ink); font-size: 2.05rem; line-height: 1.08; font-weight: 850; }
.blue-stat-caption { color: var(--ink-faint); font-size: 0.82rem; margin-top: 0.4rem; }

/* 表格 */
.blue-table-wrap {
    width: 100%;
    overflow: auto;
    border: 1px solid var(--line);
    border-radius: var(--card-radius);
    background: #FFFFFF;
    box-shadow: var(--shadow);
    margin: 0.55rem 0 1rem 0;
}
.blue-table-wrap table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.92rem;
    color: var(--ink);
}
.blue-table-wrap thead th {
    position: sticky; top: 0; z-index: 2;
    background: linear-gradient(180deg, var(--blue-50) 0%, var(--blue-100) 100%);
    color: var(--blue-deep);
    font-weight: 750;
    text-align: left;
    padding: 0.72rem 0.8rem;
    border-bottom: 1px solid var(--line);
    white-space: nowrap;
}
.blue-table-wrap tbody td {
    padding: 0.68rem 0.8rem;
    border-bottom: 1px solid var(--line-soft);
    vertical-align: top;
}
.blue-table-wrap tbody tr:nth-child(even) td { background: var(--blue-25); }
.blue-table-wrap tbody tr:hover td { background: #EFF6FF; }
.blue-table-wrap tbody tr:last-child td { border-bottom: 0; }

/* 表格内迷你进度条 */
.mini-progress {
    position: relative;
    width: 120px; height: 10px;
    background: var(--line-soft);
    border-radius: 999px;
    overflow: hidden;
    display: inline-block;
    vertical-align: middle;
    margin-right: 0.5rem;
}
.mini-progress > span {
    position: absolute; left: 0; top: 0; bottom: 0;
    background: linear-gradient(90deg, #93C5FD, var(--blue));
    border-radius: 999px;
}

/* 徽章 */
.badge-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 0.6rem; margin: 0.6rem 0 1rem 0; }
.badge-card {
    border: 1px solid var(--line);
    border-radius: 1rem;
    padding: 0.75rem 0.6rem;
    text-align: center;
    background: linear-gradient(180deg, #FFFFFF, var(--blue-25));
    box-shadow: var(--shadow);
}
.badge-card.locked { opacity: 0.38; filter: grayscale(1); box-shadow: none; }
.badge-emoji { font-size: 1.9rem; line-height: 1.2; }
.badge-name { font-weight: 800; color: var(--ink); margin-top: 0.25rem; font-size: 0.92rem; }
.badge-desc { color: var(--ink-faint); font-size: 0.76rem; margin-top: 0.15rem; line-height: 1.45; }

/* 个人进度环 */
.ring-wrap { display: flex; align-items: center; gap: 1.2rem; flex-wrap: wrap; }
.ring-meta .ring-title { color: var(--ink-soft); font-weight: 700; font-size: 0.95rem; }
.ring-meta .ring-big { color: var(--ink); font-weight: 850; font-size: 1.7rem; letter-spacing: -0.02em; }
.ring-meta .ring-sub { color: var(--ink-faint); font-size: 0.86rem; margin-top: 0.2rem; }

.soft-note { color: var(--ink-faint); font-size: 0.95rem; line-height: 1.8; }

@media (max-width: 640px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 1.1rem; }
    div[data-testid="stMetricValue"] { font-size: 1.35rem; }
    .mini-progress { width: 76px; }
}
</style>
"""


def inject_app_style():
    # Streamlit 每次 rerun 都重绘页面，CSS 需要每次注入（很轻量）。
    st.markdown(APP_CSS, unsafe_allow_html=True)
