"""多个页面共用的统计表构建函数。"""
import pandas as pd
import streamlit as st

from core.config import (
    ENERGY_CREDIT_CAP_MIN,
    MONTHLY_TARGET_CHECKINS_PER_PERSON,
    MONTHLY_TARGET_MINUTES_PER_CHECKIN,
    get_active_members,
    get_members,
)
from core.rules import (
    ending_true_streak,
    explode_activity_records,
    format_goal_credit,
    get_member_monthly_target_checkins,
    get_monthly_goal_settings,
    longest_true_streak,
    summarize_goal_credits,
)


def make_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["姓名", "总运动分钟", "打卡天数", "运动种类数", "打卡次数", "平均每次分钟"]
        )

    base = df.groupby("name", as_index=False).agg(
        总运动分钟=("duration_min", "sum"),
        打卡天数=("activity_date", "nunique"),
        打卡次数=("id", "count"),
    )

    exploded = explode_activity_records(df)
    if exploded.empty:
        diversity = pd.DataFrame(columns=["name", "运动种类数"])
    else:
        diversity = exploded.groupby("name", as_index=False).agg(
            运动种类数=("activity_type", "nunique")
        )

    out = base.merge(diversity, on="name", how="left").fillna({"运动种类数": 0})
    out["运动种类数"] = out["运动种类数"].astype(int)
    out["平均每次分钟"] = (out["总运动分钟"] / out["打卡次数"]).round(1)
    out = out.rename(columns={"name": "姓名"})
    return out.sort_values(["总运动分钟", "打卡天数", "运动种类数"], ascending=False)


def make_activity_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["运动类型", "总运动分钟", "参与人数", "打卡次数"]
    exploded = explode_activity_records(df) if not df.empty else pd.DataFrame()
    if exploded.empty:
        return pd.DataFrame(columns=columns)

    out = (
        exploded.groupby("activity_type", as_index=False)
        .agg(
            总运动分钟=("duration_share", "sum"),
            参与人数=("name", "nunique"),
            打卡次数=("id", "nunique"),
        )
        .rename(columns={"activity_type": "运动类型"})
    )
    out["总运动分钟"] = out["总运动分钟"].round(1)
    return out.sort_values(["总运动分钟", "参与人数", "打卡次数"], ascending=False)


def make_diversity_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    columns = ["姓名", "运动种类数", "运动类型", "总运动分钟", "打卡天数"]
    exploded = explode_activity_records(df) if not df.empty else pd.DataFrame()
    if exploded.empty:
        return pd.DataFrame(columns=columns)

    diversity = (
        exploded.groupby("name").agg(运动种类数=("activity_type", "nunique")).reset_index()
    )
    totals = (
        df.groupby("name")
        .agg(总运动分钟=("duration_min", "sum"), 打卡天数=("activity_date", "nunique"))
        .reset_index()
    )
    activity_list = (
        exploded.groupby("name")["activity_type"]
        .apply(lambda x: "、".join(sorted(set(x))))
        .reset_index(name="运动类型")
    )
    out = (
        diversity.merge(totals, on="name", how="left")
        .merge(activity_list, on="name", how="left")
        .rename(columns={"name": "姓名"})
    )
    return out.sort_values(["运动种类数", "总运动分钟", "打卡天数"], ascending=False)


def make_daily_presence_table(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    members = get_members()
    if not members:
        members = (
            sorted(df["name"].dropna().unique().tolist()) if not df.empty else []
        )

    date_index = pd.date_range(start_date, end_date).date

    if df.empty:
        presence = pd.DataFrame(index=date_index, columns=members).fillna("—")
        presence.index.name = "日期"
        return presence.reset_index()

    temp = df.copy()
    temp["has_checkin"] = "✅"
    pivot = (
        temp.pivot_table(
            index="activity_date", columns="name", values="has_checkin", aggfunc="first"
        )
        .reindex(date_index)
        .reindex(columns=members)
        .fillna("—")
    )
    pivot.index.name = "日期"
    return pivot.reset_index()


def make_cumulative_minutes(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    date_index = pd.date_range(start_date, end_date).date
    daily = df.groupby(["activity_date", "name"], as_index=False).agg(
        duration_min=("duration_min", "sum")
    )
    pivot = (
        daily.pivot_table(
            index="activity_date", columns="name", values="duration_min", aggfunc="sum"
        )
        .reindex(date_index)
        .fillna(0)
    )
    cumulative = pivot.cumsum()
    cumulative.index = pd.to_datetime(cumulative.index)
    return cumulative


# -----------------------------
# 月度目标
# -----------------------------

def make_current_month_goal_table(df_month_to_date: pd.DataFrame) -> pd.DataFrame:
    active_members = get_active_members()
    target_checkins, target_minutes = get_monthly_goal_settings()

    columns = [
        "姓名", "月目标次数", "有效运动次数", "总打卡次数", "总运动分钟",
        "半次运动达标记录数", "半次运动计入次数", "还差有效运动次数",
        "本月状态", "达标提示",
    ]
    if not active_members:
        return pd.DataFrame(columns=columns)

    base = pd.DataFrame({"姓名": active_members})
    base["月目标次数"] = base["姓名"].apply(
        lambda n: get_member_monthly_target_checkins(n, target_checkins)
    )

    if df_month_to_date.empty:
        out = base.copy()
        for col, default in [
            ("有效运动次数", 0.0), ("总打卡次数", 0), ("总运动分钟", 0),
            ("半次运动达标记录数", 0), ("半次运动计入次数", 0.0),
        ]:
            out[col] = default
    else:
        df = df_month_to_date[df_month_to_date["name"].isin(active_members)].copy()
        summary = summarize_goal_credits(df, ["name"], target_minutes).rename(
            columns={"name": "姓名"}
        )
        out = base.merge(summary, on="姓名", how="left").fillna(
            {
                "有效运动次数": 0.0, "总打卡次数": 0, "总运动分钟": 0,
                "半次运动达标记录数": 0, "半次运动计入次数": 0.0,
            }
        )

    out["月目标次数"] = out["月目标次数"].astype(int)
    out["有效运动次数"] = out["有效运动次数"].astype(float)
    out["总打卡次数"] = out["总打卡次数"].astype(int)
    out["总运动分钟"] = out["总运动分钟"].astype(int)
    out["半次运动达标记录数"] = out["半次运动达标记录数"].astype(int)
    out["半次运动计入次数"] = out["半次运动计入次数"].astype(float)

    out["还差有效运动次数"] = (out["月目标次数"] - out["有效运动次数"]).clip(lower=0)
    out["本月状态"] = out["还差有效运动次数"].apply(
        lambda x: "✅ 已达标" if float(x) <= 0 else "未达标"
    )
    out["达标提示"] = out["还差有效运动次数"].apply(
        lambda x: "本月已达标" if float(x) <= 0
        else f"还差 {format_goal_credit(x)} 次有效运动"
    )

    return out[columns].sort_values(
        ["有效运动次数", "总运动分钟", "总打卡次数"], ascending=False
    )


def make_monthly_goal_history(df_all: pd.DataFrame, today) -> pd.DataFrame:
    active_members = get_active_members()
    target_checkins, target_minutes = get_monthly_goal_settings()

    columns = [
        "姓名", "月份", "月目标次数", "有效运动次数", "总打卡次数", "总运动分钟",
        "半次运动达标记录数", "半次运动计入次数", "是否达标", "还差有效运动次数",
    ]
    if not active_members:
        return pd.DataFrame(columns=columns)

    current_month = pd.Period(today, freq="M")
    if df_all.empty:
        months = [current_month]
    else:
        min_month = pd.Period(min(df_all["activity_date"]), freq="M")
        months = list(pd.period_range(min_month, current_month, freq="M"))

    skeleton = pd.MultiIndex.from_product(
        [active_members, months], names=["姓名", "月份"]
    ).to_frame(index=False)
    skeleton["月目标次数"] = skeleton["姓名"].apply(
        lambda n: get_member_monthly_target_checkins(n, target_checkins)
    )

    if df_all.empty:
        summary = pd.DataFrame(columns=["姓名", "月份"])
    else:
        df = df_all[df_all["name"].isin(active_members)].copy()
        df["月份"] = pd.to_datetime(df["activity_date"]).dt.to_period("M")
        summary = summarize_goal_credits(df, ["name", "月份"], target_minutes).rename(
            columns={"name": "姓名"}
        )

    out = skeleton.merge(summary, on=["姓名", "月份"], how="left").fillna(
        {
            "有效运动次数": 0.0, "总打卡次数": 0, "总运动分钟": 0,
            "半次运动达标记录数": 0, "半次运动计入次数": 0.0,
        }
    )

    out["有效运动次数"] = out["有效运动次数"].astype(float)
    out["总打卡次数"] = out["总打卡次数"].astype(int)
    out["总运动分钟"] = out["总运动分钟"].astype(int)
    out["半次运动达标记录数"] = out["半次运动达标记录数"].astype(int)
    out["半次运动计入次数"] = out["半次运动计入次数"].astype(float)
    out["是否达标"] = out["有效运动次数"] >= out["月目标次数"]
    out["还差有效运动次数"] = (out["月目标次数"] - out["有效运动次数"]).clip(lower=0)
    out["月份"] = out["月份"].astype(str)
    return out


def make_goal_streak_table(goal_history: pd.DataFrame, today) -> pd.DataFrame:
    active_members = get_active_members()
    target_checkins, _ = get_monthly_goal_settings()
    current_month = str(pd.Period(today, freq="M"))

    columns = [
        "姓名", "累计达标月数", "统计月数", "累计达标率", "历史连续达标月数",
        "最长连续达标月数", "本月目标次数", "本月有效运动次数",
        "本月还差有效运动次数", "本月状态", "本月提示",
    ]
    if goal_history.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for name in active_members:
        current_target = get_member_monthly_target_checkins(name, target_checkins)
        person = goal_history[goal_history["姓名"] == name].sort_values("月份")
        completed = person[person["月份"] < current_month]
        completed_status = completed["是否达标"].tolist()

        current_row = person[person["月份"] == current_month]
        if current_row.empty:
            current_valid, current_remaining, current_achieved = 0.0, float(current_target), False
        else:
            current_target = int(current_row.iloc[0].get("月目标次数", current_target))
            current_valid = float(current_row.iloc[0]["有效运动次数"])
            current_remaining = float(current_row.iloc[0]["还差有效运动次数"])
            current_achieved = bool(current_row.iloc[0]["是否达标"])

        total_months = len(person)
        achieved_months = int(person["是否达标"].sum())
        rate = achieved_months / total_months * 100 if total_months > 0 else 0

        rows.append(
            {
                "姓名": name,
                "累计达标月数": achieved_months,
                "统计月数": total_months,
                "累计达标率": f"{rate:.1f}%",
                "历史连续达标月数": ending_true_streak(completed_status),
                "最长连续达标月数": longest_true_streak(completed_status),
                "本月目标次数": current_target,
                "本月有效运动次数": format_goal_credit(current_valid),
                "本月还差有效运动次数": format_goal_credit(current_remaining),
                "本月状态": "✅ 已达标" if current_achieved else "未达标",
                "本月提示": "本月已达标" if current_remaining <= 0
                else f"还差 {format_goal_credit(current_remaining)} 次有效运动",
                "_sort": current_valid,
            }
        )

    out = pd.DataFrame(rows)
    return (
        out.sort_values(
            ["累计达标月数", "历史连续达标月数", "最长连续达标月数", "_sort"],
            ascending=False,
        ).drop(columns=["_sort"])
    )


# -----------------------------
# 能量池
# -----------------------------

def make_energy_pool_stats(df_month: pd.DataFrame) -> dict:
    active_members = get_active_members()
    member_count = len(active_members)

    member_target_map = {
        m: get_member_monthly_target_checkins(m, MONTHLY_TARGET_CHECKINS_PER_PERSON)
        for m in active_members
    }
    target_checkins = int(sum(member_target_map.values()))
    target_energy_minutes = target_checkins * MONTHLY_TARGET_MINUTES_PER_CHECKIN

    empty = {
        "active_members": active_members,
        "member_count": member_count,
        "target_checkins": target_checkins,
        "target_energy_minutes": target_energy_minutes,
        "actual_checkins": 0,
        "actual_energy_minutes": 0,
        "actual_total_minutes": 0,
        "participant_count": 0,
        "progress": 0.0,
        "remaining_minutes": target_energy_minutes,
        "remaining_checkins_equivalent": target_checkins,
        "df_goal": pd.DataFrame(),
    }
    if df_month.empty or member_count == 0:
        return empty

    df_goal = df_month[df_month["name"].isin(active_members)].copy()
    if df_goal.empty:
        return empty

    # 长时间运动完整保留在总览，但计入能量池的分钟数封顶
    df_goal["energy_credit"] = df_goal["duration_min"].clip(upper=ENERGY_CREDIT_CAP_MIN)

    actual_energy_minutes = int(df_goal["energy_credit"].sum())
    progress = (
        actual_energy_minutes / target_energy_minutes if target_energy_minutes > 0 else 0
    )
    remaining_minutes = max(target_energy_minutes - actual_energy_minutes, 0)

    return {
        "active_members": active_members,
        "member_count": member_count,
        "target_checkins": target_checkins,
        "target_energy_minutes": target_energy_minutes,
        "actual_checkins": int(len(df_goal)),
        "actual_energy_minutes": actual_energy_minutes,
        "actual_total_minutes": int(df_goal["duration_min"].sum()),
        "participant_count": int(df_goal["name"].nunique()),
        "progress": min(progress, 1.0),
        "remaining_minutes": remaining_minutes,
        "remaining_checkins_equivalent": (
            remaining_minutes / MONTHLY_TARGET_MINUTES_PER_CHECKIN
            if MONTHLY_TARGET_MINUTES_PER_CHECKIN > 0
            else 0
        ),
        "df_goal": df_goal,
    }


def make_energy_pool_contribution_table(df_goal: pd.DataFrame) -> pd.DataFrame:
    active_members = get_active_members()

    if df_goal.empty:
        return pd.DataFrame(
            {
                "姓名": active_members,
                "月目标次数": [
                    get_member_monthly_target_checkins(n) for n in active_members
                ],
                "能量贡献": [0] * len(active_members),
                "实际运动分钟": [0] * len(active_members),
                "打卡次数": [0] * len(active_members),
            }
        )

    out = (
        df_goal.groupby("name", as_index=False)
        .agg(
            能量贡献=("energy_credit", "sum"),
            实际运动分钟=("duration_min", "sum"),
            打卡次数=("id", "count"),
        )
        .rename(columns={"name": "姓名"})
    )
    all_members = pd.DataFrame({"姓名": active_members})
    all_members["月目标次数"] = all_members["姓名"].apply(
        get_member_monthly_target_checkins
    )
    out = all_members.merge(out, on="姓名", how="left").fillna(
        {"能量贡献": 0, "实际运动分钟": 0, "打卡次数": 0}
    )
    for col in ["月目标次数", "能量贡献", "实际运动分钟", "打卡次数"]:
        out[col] = out[col].astype(int)
    return out.sort_values(["能量贡献", "打卡次数", "实际运动分钟"], ascending=False)


# -----------------------------
# 周报
# -----------------------------

def make_weekly_report(df_all: pd.DataFrame, today) -> dict | None:
    """上一个完整自然周的摘要（新增功能）。"""
    from datetime import timedelta

    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1)
    prev_week_start = last_week_start - timedelta(days=7)
    prev_week_end = last_week_start - timedelta(days=1)

    if df_all.empty:
        return None

    df_last = df_all[
        (df_all["activity_date"] >= last_week_start)
        & (df_all["activity_date"] <= last_week_end)
    ]
    df_prev = df_all[
        (df_all["activity_date"] >= prev_week_start)
        & (df_all["activity_date"] <= prev_week_end)
    ]
    if df_last.empty:
        return None

    total_min = int(df_last["duration_min"].sum())
    prev_min = int(df_prev["duration_min"].sum()) if not df_prev.empty else 0
    delta = total_min - prev_min

    by_person = df_last.groupby("name")["duration_min"].sum().sort_values(ascending=False)
    star = str(by_person.index[0])
    star_min = int(by_person.iloc[0])

    exploded = explode_activity_records(df_last)
    top_activity = ""
    if not exploded.empty:
        top_activity = str(
            exploded.groupby("activity_type")["duration_share"].sum().idxmax()
        )

    return {
        "week_range": f"{last_week_start} 至 {last_week_end}",
        "total_min": total_min,
        "delta": delta,
        "participants": int(df_last["name"].nunique()),
        "checkins": int(len(df_last)),
        "star": star,
        "star_min": star_min,
        "top_activity": top_activity,
    }
