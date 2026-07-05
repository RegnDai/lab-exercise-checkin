"""「我的」个人主页（新增）：一屏看到自己本月怎么样。

进度环 + 连续打卡 + 徽章 + 心情日历。
"""
import calendar
from html import escape

import pandas as pd
import streamlit as st

from core.config import get_active_members
from core.db import filter_by_date_range, get_month_range, get_now_local, load_checkins
from core.rules import (
    activity_emoji,
    compute_badges,
    compute_day_streak,
    format_goal_credit,
    format_mood_key,
    get_member_monthly_target_checkins,
    get_monthly_goal_settings,
    mood_emoji,
    split_mood_keys,
    summarize_goal_credits,
)
from ui.components import (
    render_badge_grid,
    render_blue_stat_card,
    render_blue_table,
    render_progress_ring,
)
from views.shared import make_monthly_goal_history


def _clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in ["nan", "none", "nat"] else text


def _build_day_tooltip(day_records: pd.DataFrame) -> str:
    lines = []
    for _, record in day_records.sort_values("submitted_at").iterrows():
        activity = escape(_clean_text(record.get("activity_type", "")).replace("（主要）", ""))
        minutes = escape(_clean_text(record.get("duration_min", "")))
        note = escape(_clean_text(record.get("note", "")))
        mood = escape(format_mood_key(record.get("mood_key")))
        item = f"<div class='diary-tip-item'><b>{mood}</b> ｜ {activity} ｜ {minutes} 分钟"
        if note:
            item += f"<br><span>{note}</span>"
        item += "</div>"
        lines.append(item)
    return "".join(lines)


def render_mood_calendar(df_person_month: pd.DataFrame, year: int, month: int):
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    by_date = {}
    if not df_person_month.empty:
        temp = df_person_month.copy()
        temp["activity_date"] = pd.to_datetime(
            temp["activity_date"], errors="coerce"
        ).dt.date
        temp = temp.dropna(subset=["activity_date"])
        for day, group in temp.groupby("activity_date"):
            by_date[day] = group.copy()

    weekday_labels = ["一", "二", "三", "四", "五", "六", "日"]

    html = ["""
        <style>
        .diary-calendar {
            width: 100%; border: 1px solid #C8D8F0; border-radius: 1.15rem;
            overflow: visible; background: #FFFFFF;
            box-shadow: 0 10px 24px rgba(37, 99, 235, 0.07); margin-top: 0.7rem;
        }
        .diary-weekdays, .diary-week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
        .diary-weekday {
            padding: 0.7rem 0.45rem; text-align: center; color: #1D4ED8; font-weight: 750;
            background: linear-gradient(180deg, #EAF2FF 0%, #DCEBFF 100%);
            border-bottom: 1px solid #C8D8F0;
        }
        .diary-day {
            position: relative; min-height: 104px; padding: 0.62rem;
            border-right: 1px solid #E5EEF8; border-bottom: 1px solid #E5EEF8; background: #FFFFFF;
        }
        .diary-week .diary-day:nth-child(7) { border-right: 0; }
        .diary-day.muted { background: #F8FBFF; color: #CBD5E1; }
        .diary-day.has-record {
            background:
                radial-gradient(circle at top right, rgba(37, 99, 235, 0.13), transparent 38%),
                linear-gradient(180deg, #FFFFFF 0%, #F4F8FF 100%);
        }
        .diary-date { color: #475569; font-size: 0.88rem; font-weight: 700; }
        .diary-moods { margin-top: 0.55rem; font-size: 1.45rem; line-height: 1.35; min-height: 2rem; }
        .diary-count { margin-top: 0.25rem; color: #64748B; font-size: 0.78rem; }
        .diary-tooltip {
            display: none; position: absolute; left: 0.45rem; top: 4.6rem;
            width: min(280px, 72vw); z-index: 20; background: #172033; color: #F8FAFC;
            border-radius: 0.9rem; padding: 0.78rem 0.85rem;
            box-shadow: 0 14px 34px rgba(15, 23, 42, 0.24);
            font-size: 0.86rem; line-height: 1.55;
        }
        .diary-tooltip::before {
            content: ""; position: absolute; top: -7px; left: 18px; width: 14px; height: 14px;
            transform: rotate(45deg); background: #172033;
        }
        .diary-tip-item { padding: 0.35rem 0; border-bottom: 1px solid rgba(255,255,255,0.13); }
        .diary-tip-item:last-child { border-bottom: 0; }
        .diary-tip-item span { color: #CBD5E1; }
        .diary-day.has-record:hover { outline: 2px solid rgba(37, 99, 235, 0.32); outline-offset: -2px; }
        .diary-day.has-record:hover .diary-tooltip { display: block; }
        @media (max-width: 760px) {
            .diary-day { min-height: 82px; padding: 0.45rem; }
            .diary-moods { font-size: 1.15rem; }
            .diary-count { display: none; }
        }
        </style>
        <div class="diary-calendar"><div class="diary-weekdays">
    """]

    for label in weekday_labels:
        html.append(f"<div class='diary-weekday'>{label}</div>")
    html.append("</div>")

    for week in weeks:
        html.append("<div class='diary-week'>")
        for day in week:
            day_records = by_date.get(day)
            classes = ["diary-day"]
            if day.month != month:
                classes.append("muted")
            if day_records is not None and not day_records.empty:
                classes.append("has-record")

            mood_keys = []
            if day_records is not None and not day_records.empty:
                for value in day_records["mood_key"].dropna().astype(str).tolist():
                    for key in split_mood_keys(value):
                        if key not in mood_keys:
                            mood_keys.append(key)

            moods = "".join(mood_emoji(k) for k in mood_keys if mood_emoji(k))
            if day_records is not None and not day_records.empty and not moods:
                emojis = []
                for v in day_records["activity_type"].dropna().astype(str).tolist():
                    e = activity_emoji(v)
                    if e and e not in emojis:
                        emojis.append(e)
                moods = "".join(emojis) or "✨"

            count_text = tooltip = ""
            if day_records is not None and not day_records.empty:
                count_text = f"<div class='diary-count'>{len(day_records)} 条记录</div>"
                tooltip = f"<div class='diary-tooltip'>{_build_day_tooltip(day_records)}</div>"

            html.append(
                f"""
                <div class="{' '.join(classes)}">
                    <div class="diary-date">{day.day}</div>
                    <div class="diary-moods">{moods}</div>
                    {count_text}{tooltip}
                </div>
                """
            )
        html.append("</div>")
    html.append("</div>")

    calendar_html = "".join(html)
    if hasattr(st, "html"):
        st.html(calendar_html)
    else:
        st.markdown(calendar_html, unsafe_allow_html=True)


def me_page():
    st.subheader("我的运动")

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取记录失败。")
        st.exception(e)
        return

    today = get_now_local().date()

    members = get_active_members()
    if not members and not df_all.empty:
        members = sorted(df_all["name"].dropna().astype(str).unique().tolist())
    if not members:
        st.info("还没有成员。")
        return

    # 记住上次选择
    default_index = 0
    remembered = st.session_state.get("me_selected_member")
    if remembered in members:
        default_index = members.index(remembered)

    name = st.selectbox("我是", members, index=default_index, key="me_selected_member")

    df_person = (
        df_all[df_all["name"].astype(str) == str(name)].copy()
        if not df_all.empty
        else pd.DataFrame()
    )

    month_start, month_end = get_month_range(today)
    df_person_month = filter_by_date_range(df_person, month_start, today)

    # ---- 本月目标进度环 ----
    _, target_minutes = get_monthly_goal_settings()
    target = get_member_monthly_target_checkins(name)

    if df_person_month.empty:
        valid_count = 0.0
        month_minutes = 0
    else:
        summary = summarize_goal_credits(df_person_month, ["name"], target_minutes)
        valid_count = float(summary.iloc[0]["有效运动次数"]) if not summary.empty else 0.0
        month_minutes = int(df_person_month["duration_min"].sum())

    progress = valid_count / target if target > 0 else 0
    remaining = max(target - valid_count, 0)

    ring_col, stat_col = st.columns([1.2, 1])
    with ring_col:
        render_progress_ring(
            progress=min(progress, 1.0),
            center_top=f"{format_goal_credit(valid_count)}/{target}",
            center_bottom="有效运动次数",
            title=f"{today.year}年{today.month}月目标",
            big_text="本月已达标 🎉" if remaining <= 0
            else f"还差 {format_goal_credit(remaining)} 次",
            sub_text=f"本月累计 {month_minutes} 分钟 ｜ 每次不少于 {target_minutes} 分钟",
        )

    dates = set(df_person["activity_date"].dropna().tolist()) if not df_person.empty else set()
    current_streak, longest_streak = compute_day_streak(dates, today)

    with stat_col:
        s1, s2 = st.columns(2)
        with s1:
            render_blue_stat_card("当前连续", f"{current_streak} 天")
        with s2:
            render_blue_stat_card("历史最长连续", f"{longest_streak} 天")

    total_minutes = int(df_person["duration_min"].sum()) if not df_person.empty else 0
    total_checkins = len(df_person)
    total_days = int(df_person["activity_date"].nunique()) if not df_person.empty else 0

    c1, c2, c3 = st.columns(3)
    with c1:
        render_blue_stat_card("累计打卡", f"{total_checkins} 次")
    with c2:
        render_blue_stat_card("累计天数", f"{total_days} 天")
    with c3:
        render_blue_stat_card("累计分钟", total_minutes)

    st.divider()

    # ---- 徽章 ----
    st.markdown("### 我的徽章")
    goal_history = make_monthly_goal_history(df_all, today)
    goal_history_person = (
        goal_history[goal_history["姓名"] == name]
        if not goal_history.empty
        else pd.DataFrame()
    )
    badges = compute_badges(df_person, goal_history_person, today)
    earned_count = sum(1 for b in badges if b["earned"])
    st.caption(f"已点亮 {earned_count} / {len(badges)} 枚。灰色的还在路上。")
    render_badge_grid(badges)

    st.divider()

    # ---- 心情日历 ----
    st.markdown("### 运动日历")
    st.caption("日期下方显示当天运动后的心情；悬浮在日期上可以看到运动内容和碎碎念。")

    months = set()
    if not df_person.empty:
        dates_dt = pd.to_datetime(df_person["activity_date"], errors="coerce").dropna()
        months.update(dates_dt.dt.to_period("M").astype(str).tolist())
    current_month = str(pd.Period(today, freq="M"))
    months.add(current_month)
    available_months = sorted(months)

    def _month_label(m):
        p = pd.Period(m, freq="M")
        return f"{p.year}年{p.month}月"

    selected_month = st.selectbox(
        "选择月份",
        available_months,
        index=available_months.index(current_month),
        format_func=_month_label,
        key="me_selected_month",
    )
    period = pd.Period(selected_month, freq="M")

    person_view = df_person.copy()
    if not person_view.empty:
        person_view["month"] = (
            pd.to_datetime(person_view["activity_date"], errors="coerce")
            .dt.to_period("M").astype(str)
        )
        person_view = person_view[person_view["month"] == selected_month]

    if not person_view.empty:
        mood_values = []
        for value in person_view["mood_key"].dropna().astype(str).tolist():
            mood_values.extend(split_mood_keys(value))
        if mood_values:
            counts = pd.Series(mood_values).value_counts()
            summary_text = "　".join(
                f"{format_mood_key(k)} × {c}" for k, c in counts.items()
            )
            st.caption(f"当月心情分布：{summary_text}")

    render_mood_calendar(person_view, period.year, period.month)

    # ---- 最近记录 ----
    with st.expander("我的最近记录"):
        if df_person.empty:
            st.info("还没有记录，去打第一卡吧。")
        else:
            recent = (
                df_person.sort_values("submitted_at", ascending=False)
                .head(20)
                .loc[:, ["activity_date", "activity_type", "duration_min", "note", "is_backfill"]]
                .rename(
                    columns={
                        "activity_date": "日期",
                        "activity_type": "运动类型",
                        "duration_min": "分钟",
                        "note": "备注",
                        "is_backfill": "补卡",
                    }
                )
            )
            recent["补卡"] = recent["补卡"].map({True: "⏪ 补卡", False: ""})
            render_blue_table(recent)
