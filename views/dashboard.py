"""看板页：总览 + 本月目标（能量池）合并，顶部加周报卡片。"""
import streamlit as st

from core.config import ENERGY_CREDIT_CAP_MIN, MONTHLY_TARGET_MINUTES_PER_CHECKIN, get_active_members
from core.db import (
    filter_by_date_range,
    get_month_range,
    get_now_local,
    get_week_range,
    load_checkins,
)
from core.rules import (
    format_goal_credit,
    get_monthly_goal_settings,
    get_monthly_target_rule_text,
)
from ui.components import (
    render_blue_bar_chart,
    render_blue_stat_card,
    render_blue_table,
    render_energy_bowl,
    render_interactive_cumulative_minutes_chart,
)
from views.shared import (
    make_activity_leaderboard,
    make_cumulative_minutes,
    make_current_month_goal_table,
    make_daily_presence_table,
    make_diversity_leaderboard,
    make_energy_pool_contribution_table,
    make_energy_pool_stats,
    make_goal_streak_table,
    make_leaderboard,
    make_monthly_goal_history,
    make_weekly_report,
)


def _render_weekly_report(df_all, today):
    report = make_weekly_report(df_all, today)
    if not report:
        return

    delta_text = (
        f"环比 +{report['delta']}" if report["delta"] >= 0 else f"环比 {report['delta']}"
    )
    st.markdown("### 📬 上周周报")
    st.caption(report["week_range"])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_blue_stat_card("总分钟", report["total_min"], delta_text)
    with c2:
        render_blue_stat_card("参与人数", report["participants"])
    with c3:
        render_blue_stat_card("本周之星", report["star"], f"{report['star_min']} 分钟")
    with c4:
        render_blue_stat_card("最热运动", report["top_activity"] or "—")

    share_text = (
        f"🏃 实验室运动周报（{report['week_range']}）\n"
        f"总运动 {report['total_min']} 分钟（{delta_text}），"
        f"{report['participants']} 人参与，共 {report['checkins']} 次打卡。\n"
        f"本周之星：{report['star']}（{report['star_min']} 分钟）"
        + (f"，最热运动：{report['top_activity']}。" if report["top_activity"] else "。")
    )
    with st.expander("复制文字版周报（发到群里）"):
        st.code(share_text, language=None)

    st.divider()


def dashboard_page():
    st.subheader("运动看板")

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取打卡数据失败。")
        st.exception(e)
        return

    today = get_now_local().date()
    week_start, week_end = get_week_range(today)
    month_start, month_end_full = get_month_range(today)

    if df_all.empty:
        st.info("还没有记录。")
        return

    df_week = filter_by_date_range(df_all, week_start, week_end)
    df_month = filter_by_date_range(df_all, month_start, today)
    df_month_full = filter_by_date_range(df_all, month_start, month_end_full)
    df_today = filter_by_date_range(df_all, today, today)

    st.caption(
        f"今日 {today} ｜ 本周 {week_start} 至 {week_end} ｜ "
        f"本月至今 {month_start} 至 {today}"
    )

    tab_overview, tab_goal, tab_pool = st.tabs(["总览", "本月达标", "能量池"])

    # ============ 总览 ============
    with tab_overview:
        _render_weekly_report(df_all, today)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            render_blue_stat_card(
                "今日参与人数", df_today["name"].nunique() if not df_today.empty else 0
            )
        with c2:
            render_blue_stat_card(
                "本周总分钟", int(df_week["duration_min"].sum()) if not df_week.empty else 0
            )
        with c3:
            render_blue_stat_card("本月总分钟", int(df_month["duration_min"].sum()))
        with c4:
            render_blue_stat_card("本月参与人数", df_month["name"].nunique())

        st.divider()

        left, right = st.columns(2)
        with left:
            st.markdown("### 本周运动时长")
            weekly_board = make_leaderboard(df_week)
            if weekly_board.empty:
                st.info("本周还没有打卡记录。")
            else:
                render_blue_table(weekly_board)
                render_blue_bar_chart(weekly_board, "姓名", "总运动分钟", height=280)

        with right:
            st.markdown("### 本月运动时长")
            monthly_board = make_leaderboard(df_month)
            if monthly_board.empty:
                st.info("本月还没有打卡记录。")
            else:
                render_blue_table(monthly_board)
                render_blue_bar_chart(monthly_board, "姓名", "总运动分钟", height=280)

        st.divider()

        st.markdown("### 本月累计运动时长")
        cumulative = make_cumulative_minutes(df_month, month_start, today)
        render_interactive_cumulative_minutes_chart(cumulative)

        st.divider()

        st.markdown("### 运动类型分布")
        activity_board = make_activity_leaderboard(df_month)
        if activity_board.empty:
            st.info("本月还没有运动类型数据。")
        else:
            render_blue_table(activity_board)
            render_blue_bar_chart(activity_board, "运动类型", "总运动分钟", height=280)

        st.divider()

        st.markdown("### 运动多样性")
        diversity_board = make_diversity_leaderboard(df_month)
        if diversity_board.empty:
            st.info("本月还没有运动多样性数据。")
        else:
            render_blue_table(diversity_board)

        st.divider()

        st.markdown("### 本周记录")
        render_blue_table(make_daily_presence_table(df_week, week_start, week_end))

        with st.expander("最近记录"):
            recent = (
                df_all.sort_values("submitted_at", ascending=False)
                .head(30)
                .loc[
                    :,
                    [
                        "name", "activity_date", "activity_type",
                        "duration_min", "note", "submitted_at", "is_backfill",
                    ],
                ]
                .rename(
                    columns={
                        "name": "姓名",
                        "activity_date": "运动日期",
                        "activity_type": "运动类型",
                        "duration_min": "运动分钟",
                        "note": "备注",
                        "submitted_at": "提交时间",
                        "is_backfill": "补卡",
                    }
                )
            )
            recent["补卡"] = recent["补卡"].map({True: "⏪ 补卡", False: ""})
            render_blue_table(recent)

    # ============ 本月达标 ============
    with tab_goal:
        target_checkins, target_minutes = get_monthly_goal_settings()
        st.caption(
            f"规则：{get_monthly_target_rule_text()}；每次运动不少于 {target_minutes} 分钟。"
        )

        monthly_goal_table = make_current_month_goal_table(df_month)
        achieved = (
            int((monthly_goal_table["本月状态"] == "✅ 已达标").sum())
            if not monthly_goal_table.empty
            else 0
        )
        active_count = len(get_active_members())

        g1, g2, g3 = st.columns(3)
        with g1:
            st.metric("已达标", f"{achieved} / {active_count}")
        with g2:
            st.metric("未达标", max(active_count - achieved, 0))
        with g3:
            rate = achieved / active_count * 100 if active_count > 0 else 0
            st.metric("达标率", f"{rate:.1f}%")

        display = monthly_goal_table.copy()
        display["半次运动计入次数"] = display["半次运动计入次数"].apply(format_goal_credit)
        display["还差有效运动次数"] = display["还差有效运动次数"].apply(format_goal_credit)
        display = display.rename(
            columns={
                "月目标次数": "目标",
                "有效运动次数": "进度",
                "总打卡次数": "打卡",
                "总运动分钟": "分钟",
                "还差有效运动次数": "还差",
                "本月状态": "状态",
                "达标提示": "提示",
            }
        )
        # 「进度」列渲染成迷你进度条
        render_blue_table(display, progress_cols={"进度": "目标"})

        st.divider()

        st.markdown("### 长期记录")
        st.caption("连续月份只统计已结束月份；本月进度单独显示。")

        goal_history = make_monthly_goal_history(df_all, today)
        streak_view = make_goal_streak_table(goal_history, today).rename(
            columns={
                "累计达标月数": "达标月数",
                "统计月数": "统计月份",
                "历史连续达标月数": "当前连续",
                "最长连续达标月数": "最长连续",
                "本月有效运动次数": "本月有效",
                "本月还差有效运动次数": "本月还差",
                "本月状态": "状态",
                "本月提示": "提示",
            }
        )
        render_blue_table(streak_view)

        with st.expander("每月明细"):
            history_view = goal_history.copy()
            history_view["是否达标"] = history_view["是否达标"].map(
                {True: "✅ 已达标", False: "未达标"}
            )
            history_view["有效运动次数"] = history_view["有效运动次数"].apply(format_goal_credit)
            history_view["半次运动计入次数"] = history_view["半次运动计入次数"].apply(
                format_goal_credit
            )
            history_view["还差有效运动次数"] = history_view["还差有效运动次数"].apply(
                format_goal_credit
            )
            history_view = history_view.rename(
                columns={
                    "月目标次数": "目标",
                    "有效运动次数": "有效次数",
                    "总打卡次数": "打卡",
                    "总运动分钟": "分钟",
                    "是否达标": "状态",
                    "还差有效运动次数": "还差",
                }
            )
            render_blue_table(
                history_view.sort_values(["月份", "姓名"], ascending=[False, True])
            )

    # ============ 能量池 ============
    with tab_pool:
        stats = make_energy_pool_stats(df_month_full)
        progress_percent = stats["progress"] * 100

        st.caption(
            f"{month_start} 至 {month_end_full} ｜ 截至 {today} ｜ {stats['member_count']} 人"
        )
        st.markdown(
            f"""
            达标次数：**{get_monthly_target_rule_text()}**；
            每次运动 **{MONTHLY_TARGET_MINUTES_PER_CHECKIN} 分钟**。
            每条记录最多计入 **{ENERGY_CREDIT_CAP_MIN} 分钟**；多出来的时间仍会完整保留在总览里。
            """
        )

        st.markdown(f"### 能量池 {progress_percent:.1f}%")
        render_energy_bowl(stats["progress"])

        r1c1, r1c2 = st.columns(2)
        r2c1, r2c2 = st.columns(2)
        with r1c1:
            st.metric(
                "已积累",
                f"{stats['actual_energy_minutes']} / {stats['target_energy_minutes']} 分钟",
            )
        with r1c2:
            st.metric("还差", f"{stats['remaining_minutes']} 分钟")
        with r2c1:
            st.metric("约需", f"{stats['remaining_checkins_equivalent']:.1f} 次")
        with r2c2:
            st.metric("参与", f"{stats['participant_count']} / {stats['member_count']}")

        st.divider()

        if stats["member_count"] == 0:
            st.warning("还没有设置参与成员。")
        elif stats["progress"] >= 1:
            st.success("能量池已装满。")
        elif stats["progress"] >= 0.75:
            st.info("快满了。")
        elif stats["progress"] >= 0.4:
            st.info("已经过半，继续加一点。")
        else:
            st.info("刚开始，慢慢来。")

        st.divider()

        st.markdown("### 成员贡献")
        contribution = make_energy_pool_contribution_table(stats["df_goal"])
        render_blue_table(
            contribution.rename(
                columns={"能量贡献": "贡献", "实际运动分钟": "实际分钟"}
            )
        )
        if not contribution.empty:
            render_blue_bar_chart(contribution, "姓名", "能量贡献", height=280)

        st.caption("能量池看共同进度；总览保留每个人的完整记录。")
