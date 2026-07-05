"""可复用 UI 组件。"""
from html import escape

import pandas as pd
import streamlit as st

from core.rules import format_goal_credit


def _st_html(html: str):
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)


def render_blue_table(
    dataframe: pd.DataFrame,
    hide_index: bool = True,
    height: int | None = None,
    progress_cols: dict[str, str] | None = None,
    **_,
):
    """蓝色主题表格。

    progress_cols: {列名: 最大值列名或数字}，把该列渲染成迷你进度条。
    """
    if dataframe is None or dataframe.empty:
        st.info("暂无数据。")
        return

    df = dataframe.copy()
    df.columns.name = None
    df.index.name = None

    if progress_cols:
        # 需要 escape=False 才能渲染进度条 HTML，
        # 因此先把其余所有列手动 escape，避免备注等用户内容注入 HTML。
        bar_cols = set(progress_cols.keys())
        for col in df.columns:
            if col not in bar_cols:
                df[col] = df[col].map(lambda v: escape(str(v)))

        for col, max_ref in progress_cols.items():
            if col not in df.columns:
                continue

            def _bar(row, col=col, max_ref=max_ref):
                try:
                    value = float(row[col])
                except (TypeError, ValueError):
                    return escape(str(row[col]))
                if isinstance(max_ref, str) and max_ref in row.index:
                    try:
                        max_value = float(row[max_ref])
                    except (TypeError, ValueError):
                        max_value = 0
                else:
                    max_value = float(max_ref)
                pct = min(max(value / max_value, 0), 1) * 100 if max_value > 0 else 0
                label = f"{format_goal_credit(value)}/{format_goal_credit(max_value)}"
                return (
                    f"<span class='mini-progress'><span style='width:{pct:.0f}%'></span></span>"
                    f"{escape(label)}"
                )

            df[col] = df.apply(_bar, axis=1)

    escape_html = not bool(progress_cols)
    html = df.to_html(
        index=not hide_index, escape=escape_html, border=0, classes="blue-data-table"
    )
    max_height_style = f"max-height: {int(height)}px;" if height else ""
    st.markdown(
        f'<div class="blue-table-wrap" style="{max_height_style}">{html}</div>',
        unsafe_allow_html=True,
    )


def render_blue_stat_card(label: str, value, caption: str | None = None):
    caption_html = (
        f"<div class='blue-stat-caption'>{escape(str(caption))}</div>" if caption else ""
    )
    st.markdown(
        f"""
        <div class="blue-stat-card">
            <div class="blue-stat-label">{escape(str(label))}</div>
            <div class="blue-stat-value">{escape(str(value))}</div>
            {caption_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_progress_ring(
    progress: float,
    center_top: str,
    center_bottom: str,
    title: str,
    big_text: str,
    sub_text: str,
    size: int = 148,
):
    """个人主页的进度环（类似健身环）。progress: 0~1。"""
    progress = max(0.0, min(1.0, float(progress)))
    radius = 62
    circumference = 2 * 3.14159 * radius
    dash = circumference * progress

    st.markdown(
        f"""
        <div class="ring-wrap">
          <svg width="{size}" height="{size}" viewBox="0 0 148 148" role="img"
               aria-label="{escape(title)} {progress * 100:.0f}%">
            <circle cx="74" cy="74" r="{radius}" fill="none"
                    stroke="#E5EEF8" stroke-width="14"/>
            <circle cx="74" cy="74" r="{radius}" fill="none"
                    stroke="url(#ringGrad)" stroke-width="14" stroke-linecap="round"
                    stroke-dasharray="{dash:.1f} {circumference:.1f}"
                    transform="rotate(-90 74 74)"
                    style="transition: stroke-dasharray 0.6s ease;"/>
            <defs>
              <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#93C5FD"/>
                <stop offset="100%" stop-color="#1D4ED8"/>
              </linearGradient>
            </defs>
            <text x="74" y="70" text-anchor="middle"
                  font-size="26" font-weight="850" fill="#172033">{escape(center_top)}</text>
            <text x="74" y="94" text-anchor="middle"
                  font-size="13" fill="#64748B">{escape(center_bottom)}</text>
          </svg>
          <div class="ring-meta">
            <div class="ring-title">{escape(title)}</div>
            <div class="ring-big">{escape(big_text)}</div>
            <div class="ring-sub">{escape(sub_text)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_badge_grid(badges: list[dict]):
    # 注意：必须生成不含换行/缩进的紧凑 HTML。
    # st.markdown 的 HTML 块遇到空行会中断，后续缩进行会被当成
    # Markdown 代码块原样显示（曾导致徽章渲染成源码）。
    cards = []
    for b in badges:
        locked = "" if b["earned"] else " locked"
        cards.append(
            f'<div class="badge-card{locked}" title="{escape(b["desc"])}">'
            f'<div class="badge-emoji">{b["emoji"]}</div>'
            f'<div class="badge-name">{escape(b["name"])}</div>'
            f'<div class="badge-desc">{escape(b["desc"])}</div>'
            f"</div>"
        )
    _st_html(f"<div class='badge-grid'>{''.join(cards)}</div>")


def render_energy_bowl(progress: float):
    """能量碗（保留原版的招牌元素）。progress: 0~1。"""
    progress = max(0.0, min(1.0, float(progress)))
    percent = progress * 100

    _st_html(
        f"""
        <style>
        .energy-bowl-wrap {{ display: flex; justify-content: center; margin: 0.75rem 0 1.35rem 0; }}
        .energy-bowl-card {{ width: 100%; max-width: 440px; text-align: center; }}
        .energy-bowl {{
            position: relative; margin: 0 auto; width: 330px; height: 205px;
            border: 9px solid #1D4ED8; border-top: 0;
            border-radius: 0 0 170px 170px / 0 0 125px 125px;
            background: linear-gradient(180deg, #F4F8FF 0%, #EAF2FF 100%);
            overflow: hidden;
            box-shadow: inset 0 0 0 2px rgba(255,255,255,0.72), 0 14px 32px rgba(37, 99, 235, 0.12);
        }}
        .energy-bowl::before {{
            content: ""; position: absolute; left: 18px; right: 18px; top: 0; height: 18px;
            border-radius: 50%; background: rgba(255,255,255,0.42); z-index: 2;
        }}
        .energy-liquid {{
            position: absolute; left: 0; right: 0; bottom: 0; height: {percent:.1f}%;
            background:
                radial-gradient(circle at 30% 18%, rgba(255,255,255,0.32), transparent 22%),
                linear-gradient(180deg, #93C5FD 0%, #3B82F6 46%, #1D4ED8 100%);
            border-radius: 0 0 150px 150px / 0 0 110px 110px;
            transition: height 0.6s ease;
        }}
        .energy-liquid::before {{
            content: ""; position: absolute; top: -13px; left: 0; width: 100%; height: 25px;
            background: rgba(191, 219, 254, 0.65); border-radius: 50%;
        }}
        .energy-bowl-shine {{
            position: absolute; top: 25px; left: 38px; width: 34px; height: 112px;
            background: rgba(255,255,255,0.24); border-radius: 999px;
            transform: rotate(10deg); z-index: 2;
        }}
        .energy-bowl-label {{
            position: absolute; inset: 0; display: flex; flex-direction: column;
            align-items: center; justify-content: center; z-index: 3; pointer-events: none;
        }}
        .energy-bowl-percent {{
            font-size: 2.35rem; font-weight: 800; color: #172033; line-height: 1.1;
            text-shadow: 0 1px 8px rgba(255,255,255,0.62);
        }}
        .energy-bowl-text {{
            margin-top: 0.3rem; font-size: 0.98rem; color: #334155;
            text-shadow: 0 1px 8px rgba(255,255,255,0.62);
        }}
        .energy-bowl-caption {{ margin-top: 0.8rem; font-size: 0.95rem; color: #6b7280; }}
        @media (max-width: 640px) {{
            .energy-bowl {{ width: 260px; height: 165px; }}
            .energy-bowl-percent {{ font-size: 2rem; }}
            .energy-bowl-text {{ font-size: 0.92rem; }}
        }}
        </style>
        <div class="energy-bowl-wrap">
          <div class="energy-bowl-card">
            <div class="energy-bowl">
              <div class="energy-liquid"></div>
              <div class="energy-bowl-shine"></div>
              <div class="energy-bowl-label">
                <div class="energy-bowl-percent">{percent:.1f}%</div>
                <div class="energy-bowl-text">本月进度</div>
              </div>
            </div>
            <div class="energy-bowl-caption">一点一点，碗就满了。</div>
          </div>
        </div>
        """
    )


def render_interactive_cumulative_minutes_chart(cumulative_minutes: pd.DataFrame):
    """累计分钟折线图，Altair 图例可点击高亮。"""
    if cumulative_minutes.empty:
        st.info("本月还没有可展示的累计数据。")
        return

    try:
        import altair as alt
    except ImportError:
        st.caption("当前环境不支持交互式图例，暂时使用普通折线图。")
        st.line_chart(cumulative_minutes)
        return

    plot_df = cumulative_minutes.copy()
    plot_df.index.name = "日期"
    long_df = (
        plot_df.reset_index()
        .melt(id_vars="日期", var_name="姓名", value_name="累计分钟")
        .dropna(subset=["姓名", "累计分钟"])
    )
    if long_df.empty:
        st.info("本月还没有可展示的累计数据。")
        return

    selection = alt.selection_point(fields=["姓名"], bind="legend")
    chart = (
        alt.Chart(long_df)
        .mark_line(point=False)
        .encode(
            x=alt.X("日期:T", title="日期"),
            y=alt.Y("累计分钟:Q", title="累计运动时长（分钟）"),
            color=alt.Color("姓名:N", title="点击姓名高亮"),
            opacity=alt.condition(selection, alt.value(1.0), alt.value(0.08)),
            tooltip=[
                alt.Tooltip("日期:T", title="日期", format="%Y-%m-%d"),
                alt.Tooltip("姓名:N", title="姓名"),
                alt.Tooltip("累计分钟:Q", title="累计分钟"),
            ],
        )
        .add_params(selection)
        .properties(height=420)
    )
    st.caption("点击右侧图例中的名字，可以只高亮对应成员；按住 Shift 可多选。")
    st.altair_chart(chart, use_container_width=True)


def render_blue_bar_chart(df: pd.DataFrame, x_col: str, y_col: str, height: int = 320):
    """统一蓝色系柱状图（替代默认 st.bar_chart 的杂色）。"""
    if df.empty:
        return
    try:
        import altair as alt
    except ImportError:
        st.bar_chart(df.set_index(x_col)[y_col])
        return

    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
        .encode(
            x=alt.X(f"{x_col}:N", sort="-y", title=None),
            y=alt.Y(f"{y_col}:Q", title=y_col),
            color=alt.Color(
                f"{y_col}:Q",
                scale=alt.Scale(range=["#BFDBFE", "#1D4ED8"]),
                legend=None,
            ),
            tooltip=[x_col, y_col],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)
