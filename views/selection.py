"""评选页：多月统计、三项排名、多样性榜、荣誉墙、热图。"""
from html import escape

import pandas as pd
import streamlit as st

from core.config import get_active_members, get_members
from core.db import get_now_local, load_checkins
from core.rules import (
    explode_activity_records,
    format_goal_credit,
    get_member_monthly_target_checkins,
    get_monthly_goal_settings,
    get_monthly_target_rule_text,
    summarize_goal_credits,
)
from core.config import ACTIVITY_TYPE_SEPARATOR
from ui.components import render_blue_table


# -----------------------------
# 工具
# -----------------------------

def _selection_active_members(df_all: pd.DataFrame) -> list[str]:
    active = get_active_members()
    if active:
        return active
    members = get_members()
    if members:
        return members
    if not df_all.empty and "name" in df_all.columns:
        return sorted(df_all["name"].dropna().astype(str).unique().tolist())
    return []


def _available_months(df_all: pd.DataFrame, today) -> list[str]:
    months = set()
    if not df_all.empty and "activity_date" in df_all.columns:
        dates = pd.to_datetime(df_all["activity_date"], errors="coerce").dropna()
        if not dates.empty:
            months.update(dates.dt.to_period("M").astype(str).tolist())
    months.add(str(pd.Period(today, freq="M")))
    return sorted(months)


def _default_months(available_months: list[str], today) -> list[str]:
    try:
        count = int(st.secrets.get("SELECTION_DEFAULT_MONTHS", 3))
    except (TypeError, ValueError):
        count = 3
    count = max(1, min(count, 24))
    if not available_months:
        return [str(pd.Period(today, freq="M"))]
    return available_months[-count:]


def _month_label(month_value: str) -> str:
    try:
        period = pd.Period(month_value, freq="M")
        return f"{period.year}年{period.month}月"
    except (ValueError, TypeError):
        return str(month_value)


# -----------------------------
# 评选统计表
# -----------------------------

def make_selection_tables(df_all: pd.DataFrame, today, selected_months: list[str]) -> dict:
    target_checkins, target_minutes = get_monthly_goal_settings()
    active_members = _selection_active_members(df_all)

    selected_months = sorted({str(x) for x in selected_months if str(x).strip()})
    if not selected_months:
        selected_months = [str(pd.Period(today, freq="M"))]

    if not df_all.empty:
        df_period = df_all.copy()
        df_period["activity_date"] = pd.to_datetime(
            df_period["activity_date"], errors="coerce"
        )
        df_period = df_period.dropna(subset=["activity_date"])
        df_period["selection_month"] = (
            df_period["activity_date"].dt.to_period("M").astype(str)
        )
        df_period = df_period[
            df_period["selection_month"].isin(selected_months)
        ].copy()
    else:
        df_period = pd.DataFrame()

    if active_members and not df_period.empty:
        df_period = df_period[df_period["name"].isin(active_members)].copy()

    if active_members:
        base = pd.MultiIndex.from_product(
            [active_members, selected_months], names=["name", "month"]
        ).to_frame(index=False)
    else:
        base = pd.DataFrame(columns=["name", "month"])

    if df_period.empty:
        monthly = pd.DataFrame(
            columns=[
                "name", "month", "月运动次数", "月有效运动次数", "月运动时长",
                "半次运动达标记录数", "半次运动计入次数",
            ]
        )
    else:
        temp = df_period.copy()
        temp["month"] = temp["selection_month"]
        monthly = summarize_goal_credits(temp, ["name", "month"], target_minutes).rename(
            columns={
                "总打卡次数": "月运动次数",
                "总运动分钟": "月运动时长",
                "有效运动次数": "月有效运动次数",
            }
        )

    monthly_grid = base.merge(monthly, on=["name", "month"], how="left").fillna(
        {
            "月运动次数": 0, "月有效运动次数": 0.0, "月运动时长": 0,
            "半次运动达标记录数": 0, "半次运动计入次数": 0.0,
        }
    )
    monthly_grid["月运动次数"] = monthly_grid["月运动次数"].astype(int)
    monthly_grid["月运动时长"] = monthly_grid["月运动时长"].astype(int)
    monthly_grid["月有效运动次数"] = monthly_grid["月有效运动次数"].astype(float)
    monthly_grid["月目标次数"] = (
        monthly_grid["name"]
        .apply(lambda n: get_member_monthly_target_checkins(n, target_checkins))
        .astype(int)
    )
    monthly_grid["半次运动达标记录数"] = monthly_grid["半次运动达标记录数"].astype(int)
    monthly_grid["半次运动计入次数"] = monthly_grid["半次运动计入次数"].astype(float)
    monthly_grid["月度达标"] = (
        monthly_grid["月有效运动次数"] >= monthly_grid["月目标次数"]
    )

    if not monthly_grid.empty:
        person_month = monthly_grid.groupby("name", as_index=False).agg(
            达标月份数=("月度达标", "sum"),
            统计月份数=("month", "nunique"),
            周期目标次数=("月目标次数", "sum"),
        )
    else:
        person_month = pd.DataFrame(
            {
                "name": active_members,
                "达标月份数": [0] * len(active_members),
                "统计月份数": [len(selected_months)] * len(active_members),
                "周期目标次数": [
                    get_member_monthly_target_checkins(n, target_checkins)
                    * len(selected_months)
                    for n in active_members
                ],
            }
        )

    if df_period.empty:
        totals = pd.DataFrame(
            {
                "name": active_members,
                "总运动时长": [0] * len(active_members),
                "总运动次数": [0] * len(active_members),
                "有效运动次数": [0.0] * len(active_members),
                "半次运动达标记录数": [0] * len(active_members),
                "半次运动计入次数": [0.0] * len(active_members),
            }
        )
    else:
        totals = summarize_goal_credits(df_period, ["name"], target_minutes).rename(
            columns={"总打卡次数": "总运动次数", "总运动分钟": "总运动时长"}
        )

    summary = (
        pd.DataFrame({"name": active_members})
        .merge(totals, on="name", how="left")
        .merge(person_month, on="name", how="left")
        .fillna(
            {
                "总运动时长": 0, "总运动次数": 0, "有效运动次数": 0.0,
                "半次运动达标记录数": 0, "半次运动计入次数": 0.0,
                "达标月份数": 0, "统计月份数": len(selected_months), "周期目标次数": 0,
            }
        )
    )

    summary["总运动时长"] = summary["总运动时长"].astype(int)
    summary["总运动次数"] = summary["总运动次数"].astype(int)
    summary["有效运动次数"] = summary["有效运动次数"].astype(float)
    summary["半次运动达标记录数"] = summary["半次运动达标记录数"].astype(int)
    summary["半次运动计入次数"] = summary["半次运动计入次数"].astype(float)
    summary["达标月份数"] = summary["达标月份数"].astype(int)
    summary["统计月份数"] = summary["统计月份数"].astype(int)
    summary["周期目标次数"] = summary["周期目标次数"].astype(int)

    summary["有效次数完成率"] = summary.apply(
        lambda r: r["有效运动次数"] / r["周期目标次数"] * 100
        if r["周期目标次数"] > 0
        else 0,
        axis=1,
    ).round(1)
    summary["总达标率"] = summary.apply(
        lambda r: r["达标月份数"] / r["统计月份数"] * 100 if r["统计月份数"] > 0 else 0,
        axis=1,
    ).round(1)

    summary["总时长排名"] = summary["总运动时长"].rank(method="min", ascending=False).astype(int)
    summary["有效次数排名"] = summary["有效运动次数"].rank(method="min", ascending=False).astype(int)
    summary["达标率排名"] = summary["总达标率"].rank(method="min", ascending=False).astype(int)

    summary["满勤候选"] = summary["总达标率"] >= 100
    summary["进步展示资格"] = summary["总达标率"] >= 50
    summary = summary.rename(columns={"name": "姓名"})

    summary = summary[
        [
            "姓名", "总运动时长", "总运动次数", "有效运动次数",
            "半次运动达标记录数", "半次运动计入次数", "周期目标次数",
            "有效次数完成率", "达标月份数", "统计月份数", "总达标率",
            "总时长排名", "有效次数排名", "达标率排名", "满勤候选", "进步展示资格",
        ]
    ].sort_values(["总达标率", "有效运动次数", "总运动时长"], ascending=False)

    # 按三项指标各取前三入围
    metric_specs = [
        ("总运动时长", "总运动时长", "总时长排名"),
        ("有效运动次数", "有效运动次数", "有效次数排名"),
        ("总达标率", "总达标率", "达标率排名"),
    ]
    frames = []
    for metric_name, value_col, rank_col in metric_specs:
        temp = summary[(summary[rank_col] <= 3) & (summary[value_col] > 0)].copy()
        if temp.empty:
            continue
        temp["评选指标"] = metric_name
        temp["指标值"] = temp[value_col]
        temp["名次"] = temp[rank_col]
        frames.append(temp[["姓名", "评选指标", "指标值", "名次"]])

    if frames:
        selected_candidates = pd.concat(frames, ignore_index=True)
        recommended_items = (
            selected_candidates.sort_values(["姓名", "名次"], ascending=[True, True])
            .groupby("姓名", as_index=False)
            .first()
            .sort_values(["名次", "姓名"], ascending=[True, True])
        )
    else:
        selected_candidates = pd.DataFrame(columns=["姓名", "评选指标", "指标值", "名次"])
        recommended_items = selected_candidates.copy()

    monthly_heatmap_detail = monthly_grid.rename(
        columns={"name": "姓名", "month": "月份"}
    ).copy()

    monthly_detail = monthly_heatmap_detail.copy()
    if not monthly_detail.empty:
        monthly_detail["月份"] = monthly_detail["月份"].map(_month_label)
        monthly_detail["月有效运动次数"] = monthly_detail["月有效运动次数"].apply(
            format_goal_credit
        )
        monthly_detail["半次运动计入次数"] = monthly_detail["半次运动计入次数"].apply(
            format_goal_credit
        )
        monthly_detail["月度达标"] = monthly_detail["月度达标"].map(
            {True: "是", False: "否"}
        )

    # 多样性榜
    diversity_columns = [
        "多样性排名", "姓名", "运动种类数", "运动类型",
        "有效运动次数", "总运动次数", "总运动时长", "总达标率",
    ]
    diversity_records = (
        explode_activity_records(df_period) if not df_period.empty else pd.DataFrame()
    )
    if diversity_records.empty:
        diversity_board = pd.DataFrame(columns=diversity_columns)
    else:
        diversity_board = (
            diversity_records.groupby("name")
            .agg(
                运动种类数=("activity_type", "nunique"),
                运动类型=(
                    "activity_type",
                    lambda values: ACTIVITY_TYPE_SEPARATOR.join(
                        sorted({str(v).strip() for v in values if str(v).strip()})
                    ),
                ),
            )
            .reset_index()
            .rename(columns={"name": "姓名"})
            .merge(
                summary[["姓名", "有效运动次数", "总运动次数", "总运动时长", "总达标率"]],
                on="姓名",
                how="left",
            )
            .fillna(
                {"有效运动次数": 0.0, "总运动次数": 0, "总运动时长": 0, "总达标率": 0.0}
            )
        )
        diversity_board["运动种类数"] = diversity_board["运动种类数"].astype(int)
        diversity_board["总运动次数"] = diversity_board["总运动次数"].astype(int)
        diversity_board["总运动时长"] = diversity_board["总运动时长"].astype(int)
        diversity_board["有效运动次数"] = diversity_board["有效运动次数"].astype(float)
        diversity_board["总达标率"] = diversity_board["总达标率"].astype(float)
        diversity_board = diversity_board.sort_values(
            ["运动种类数", "有效运动次数", "总运动时长", "总运动次数"], ascending=False
        ).reset_index(drop=True)
        diversity_board.insert(0, "多样性排名", range(1, len(diversity_board) + 1))

    return {
        "summary": summary,
        "selected_candidates": selected_candidates,
        "recommended_items": recommended_items,
        "full_attendance": summary[summary["满勤候选"]].copy(),
        "progress_eligible": summary[summary["进步展示资格"]].copy(),
        "below_50": summary[summary["总达标率"] < 50].copy(),
        "monthly_detail": monthly_detail,
        "monthly_heatmap_detail": monthly_heatmap_detail,
        "diversity_board": diversity_board,
        "target_checkins": target_checkins,
        "target_minutes": target_minutes,
        "selected_months": selected_months,
    }


# -----------------------------
# 热图
# -----------------------------

def _heatmap_number(value) -> float:
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _heatmap_value_label(value, metric_col: str) -> str:
    number = _heatmap_number(value)
    if metric_col == "月有效运动次数":
        return format_goal_credit(number)
    if metric_col in ["月运动次数", "月运动时长"]:
        return str(int(round(number)))
    return str(value)


def _heatmap_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in [
        "true", "1", "yes", "y", "是", "✅", "✅ 已达标", "已达标",
    ]


def render_selection_metric_heatmap(
    dataframe: pd.DataFrame,
    metric_col: str,
    title: str,
    subtitle: str,
    is_boolean: bool = False,
):
    if (
        dataframe.empty
        or metric_col not in dataframe.columns
        or "姓名" not in dataframe.columns
        or "月份" not in dataframe.columns
    ):
        st.info(f"{title} 暂无数据。")
        return

    data = dataframe.copy()
    data["姓名"] = data["姓名"].astype(str)
    data["月份"] = data["月份"].astype(str)
    months = sorted(data["月份"].dropna().unique().tolist())

    if is_boolean:
        order_score = (
            data.assign(_v=data[metric_col].apply(_heatmap_bool).astype(int))
            .groupby("姓名")["_v"].sum().sort_values(ascending=False)
        )
    else:
        order_score = (
            data.assign(_v=data[metric_col].apply(_heatmap_number))
            .groupby("姓名")["_v"].sum().sort_values(ascending=False)
        )
    names = order_score.index.tolist()

    pivot = data.pivot_table(
        index="姓名", columns="月份", values=metric_col, aggfunc="first"
    ).reindex(index=names, columns=months)

    if is_boolean:
        max_value = 1.0
    else:
        numeric = [_heatmap_number(x) for x in pivot.to_numpy().flatten().tolist()]
        max_value = max(max(numeric) if numeric else 0.0, 1.0)

    month_headers = "".join(f"<th>{escape(_month_label(m))}</th>" for m in months)

    rows_html = []
    for name in names:
        cells = []
        for month in months:
            value = pivot.loc[name, month] if month in pivot.columns else None
            if is_boolean:
                achieved = _heatmap_bool(value)
                label = "✅" if achieved else "—"
                bg = "#DBEAFE" if achieved else "#F8FBFF"
                border = "#93C5FD" if achieved else "#E5EEF8"
                color = "#1D4ED8" if achieved else "#94A3B8"
            else:
                number = _heatmap_number(value)
                ratio = min(max(number / max_value, 0.0), 1.0)
                if number <= 0:
                    bg, border = "#F8FBFF", "#E5EEF8"
                else:
                    alpha = 0.10 + 0.62 * ratio
                    bg = f"rgba(37, 99, 235, {alpha:.2f})"
                    border = "rgba(37, 99, 235, 0.20)"
                color = "#0F172A"
                label = _heatmap_value_label(value, metric_col)

            cells.append(
                f"<td><div class='selection-heatmap-cell' "
                f"style='background:{bg}; border-color:{border}; color:{color};'>"
                f"{escape(label)}</div></td>"
            )
        rows_html.append(
            f"<tr><th class='selection-heatmap-name'>{escape(str(name))}</th>"
            f"{''.join(cells)}</tr>"
        )

    html = f"""
    <style>
    .selection-heatmap-card {{
        border: 1px solid #C8D8F0; border-radius: 1.15rem; background: #FFFFFF;
        box-shadow: 0 10px 24px rgba(37, 99, 235, 0.07);
        padding: 1rem 1rem 0.85rem 1rem; margin: 0.55rem 0 1rem 0;
    }}
    .selection-heatmap-title {{ color: #172033; font-weight: 800; font-size: 1.02rem; margin-bottom: 0.25rem; }}
    .selection-heatmap-subtitle {{ color: #64748B; font-size: 0.84rem; margin-bottom: 0.75rem; line-height: 1.55; }}
    .selection-heatmap-scroll {{ width: 100%; overflow-x: auto; }}
    .selection-heatmap-table {{ border-collapse: separate; border-spacing: 0.28rem; min-width: 100%; }}
    .selection-heatmap-table th {{
        color: #475569; font-size: 0.78rem; white-space: nowrap;
        text-align: center; font-weight: 750;
    }}
    .selection-heatmap-name {{
        text-align: right !important; padding-right: 0.45rem; color: #172033 !important;
        position: sticky; left: 0; background: #FFFFFF; z-index: 1;
    }}
    .selection-heatmap-cell {{
        min-width: 3.4rem; height: 2.15rem; border: 1px solid #E5EEF8;
        border-radius: 0.7rem; display: flex; align-items: center; justify-content: center;
        font-size: 0.82rem; font-weight: 800; white-space: nowrap;
    }}
    @media (max-width: 760px) {{
        .selection-heatmap-cell {{ min-width: 2.85rem; height: 2rem; font-size: 0.76rem; }}
    }}
    </style>
    <div class="selection-heatmap-card">
        <div class="selection-heatmap-title">{escape(title)}</div>
        <div class="selection-heatmap-subtitle">{escape(subtitle)}</div>
        <div class="selection-heatmap-scroll">
            <table class="selection-heatmap-table">
                <thead><tr><th></th>{month_headers}</tr></thead>
                <tbody>{''.join(rows_html)}</tbody>
            </table>
        </div>
    </div>
    """
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)


def render_selection_heatmaps(monthly_heatmap_detail: pd.DataFrame):
    st.markdown("#### 评选热图")
    st.caption(
        "颜色越深，数值越高。这里看的是每个人在所选月份里的逐月表现，"
        "比单纯排行榜更容易看出稳定性和结构。"
    )
    if monthly_heatmap_detail.empty:
        st.info("暂无可展示的热图数据。")
        return

    r1c1, r1c2 = st.columns(2)
    with r1c1:
        render_selection_metric_heatmap(
            monthly_heatmap_detail, "月有效运动次数", "有效运动次数 × 人",
            "真正计入目标的有效次数；同一天最多计入 1 次。散步 / 一万步 / 康复训练 / 台球按半次规则折算。",
        )
    with r1c2:
        render_selection_metric_heatmap(
            monthly_heatmap_detail, "月运动次数", "总运动次数 × 人",
            "所有打卡记录次数；用于观察参与频率，但不作为主要评选项。",
        )

    r2c1, r2c2 = st.columns(2)
    with r2c1:
        render_selection_metric_heatmap(
            monthly_heatmap_detail, "月运动时长", "总运动时长 × 人",
            "每人每月累计运动分钟数。",
        )
    with r2c2:
        render_selection_metric_heatmap(
            monthly_heatmap_detail, "月度达标", "是否达标 × 人",
            "每人每月是否达到本月目标；同一天多次打卡只按一次有效运动计入。",
            is_boolean=True,
        )


# -----------------------------
# 荣誉墙
# -----------------------------

def _honor_rank_label(rank_value) -> str:
    try:
        rank = int(rank_value)
    except (TypeError, ValueError):
        return str(rank_value)
    return {1: "🥇 第一名", 2: "🥈 第二名", 3: "🥉 第三名"}.get(rank, f"第 {rank} 名")


def make_monthly_honor_wall(df_all: pd.DataFrame, today) -> pd.DataFrame:
    columns = [
        "月份", "名次", "姓名", "有效运动次数", "总运动时长",
        "总运动次数", "半次运动达标记录数", "半次运动计入次数",
    ]
    if df_all.empty:
        return pd.DataFrame(columns=columns)

    _, target_minutes = get_monthly_goal_settings()
    active_members = _selection_active_members(df_all)

    df = df_all.copy()
    df["activity_date"] = pd.to_datetime(df["activity_date"], errors="coerce")
    df = df.dropna(subset=["activity_date"])
    if active_members:
        df = df[df["name"].isin(active_members)].copy()
    if df.empty:
        return pd.DataFrame(columns=columns)

    df["月份"] = df["activity_date"].dt.to_period("M").astype(str)
    monthly = summarize_goal_credits(df, ["name", "月份"], target_minutes).rename(
        columns={"name": "姓名", "总打卡次数": "总运动次数", "总运动分钟": "总运动时长"}
    )
    monthly = monthly[monthly["有效运动次数"] > 0].copy()
    if monthly.empty:
        return pd.DataFrame(columns=columns)

    monthly["有效运动次数"] = monthly["有效运动次数"].astype(float)
    monthly["总运动时长"] = monthly["总运动时长"].astype(int)
    monthly["总运动次数"] = monthly["总运动次数"].astype(int)
    monthly = monthly.sort_values(
        ["月份", "有效运动次数", "总运动时长", "姓名"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
    monthly["名次"] = monthly.groupby("月份").cumcount() + 1
    return monthly[monthly["名次"] <= 3][columns]


def render_monthly_honor_wall(df_all: pd.DataFrame, today):
    st.caption(
        "每个月单独评选前三名：先按有效运动次数排序；"
        "有效运动次数并列时，再按总运动时长排序。"
    )
    honor_wall = make_monthly_honor_wall(df_all, today)
    if honor_wall.empty:
        st.info("还没有可展示的历史前三。")
        return

    available = sorted(
        honor_wall["月份"].dropna().astype(str).unique().tolist(), reverse=True
    )
    selected = st.multiselect(
        "选择要统计的月份",
        options=available,
        default=available,
        format_func=_month_label,
        key="monthly_honor_wall_selected_months",
    )
    if not selected:
        st.warning("请至少选择一个月份。")
        return

    filtered = honor_wall[honor_wall["月份"].isin(selected)].copy()
    if filtered.empty:
        st.info("所选月份里还没有历史前三。")
        return
    filtered = filtered.sort_values(
        ["月份", "名次"], ascending=[False, True]
    ).reset_index(drop=True)

    def _rank_months(name: str, rank: int) -> str:
        months = (
            filtered[
                (filtered["姓名"].astype(str) == str(name))
                & (filtered["名次"].astype(int) == int(rank))
            ]["月份"].dropna().astype(str).unique().tolist()
        )
        months = sorted(months, reverse=True)
        if not months:
            return "—"
        return "、".join(_month_label(m) for m in months)

    names = sorted(filtered["姓名"].dropna().astype(str).unique().tolist())
    rank_count = filtered.groupby(["姓名", "名次"]).size().to_dict()

    summary_rows = []
    for name in names:
        first = int(rank_count.get((name, 1), 0))
        second = int(rank_count.get((name, 2), 0))
        third = int(rank_count.get((name, 3), 0))
        summary_rows.append(
            {
                "姓名": name,
                "第一次数": first,
                "第一月份": _rank_months(name, 1),
                "第二次数": second,
                "第二月份": _rank_months(name, 2),
                "第三次数": third,
                "第三月份": _rank_months(name, 3),
                "获奖总次数": first + second + third,
            }
        )
    honor_summary = pd.DataFrame(summary_rows)
    if not honor_summary.empty:
        honor_summary = honor_summary.sort_values(
            ["第一次数", "第二次数", "第三次数", "获奖总次数", "姓名"],
            ascending=[False, False, False, False, True],
        ).reset_index(drop=True)

    st.markdown("#### 荣誉统计")
    st.caption(
        "当前统计月份："
        + "、".join(_month_label(m) for m in sorted(selected, reverse=True))
    )
    if honor_summary.empty:
        st.info("当前筛选下没有可统计的荣誉记录。")
    else:
        render_blue_table(honor_summary)

    st.markdown("#### 历史前三明细")
    export_view = filtered.copy()
    export_view["月份"] = export_view["月份"].map(_month_label)

    display_view = export_view.copy()
    display_view["名次"] = display_view["名次"].apply(_honor_rank_label)
    display_view["有效运动次数"] = display_view["有效运动次数"].apply(format_goal_credit)
    display_view["半次运动计入次数"] = display_view["半次运动计入次数"].apply(
        format_goal_credit
    )
    render_blue_table(display_view)

    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "导出当前筛选历史前三 CSV",
            data=export_view.to_csv(index=False).encode("utf-8-sig"),
            file_name="monthly_honor_wall_top3_filtered.csv",
            mime="text/csv",
        )
    with d2:
        st.download_button(
            "导出当前筛选荣誉统计 CSV",
            data=honor_summary.to_csv(index=False).encode("utf-8-sig"),
            file_name="monthly_honor_wall_summary_filtered.csv",
            mime="text/csv",
            disabled=honor_summary.empty,
        )

    with st.expander("按月份查看"):
        for month in sorted(filtered["月份"].drop_duplicates().tolist(), reverse=True):
            month_view = filtered[filtered["月份"] == month].copy()
            month_view["月份"] = month_view["月份"].map(_month_label)
            month_view["名次"] = month_view["名次"].apply(_honor_rank_label)
            month_view["有效运动次数"] = month_view["有效运动次数"].apply(
                format_goal_credit
            )
            month_view["半次运动计入次数"] = month_view["半次运动计入次数"].apply(
                format_goal_credit
            )
            st.markdown(f"##### {_month_label(month)}")
            render_blue_table(month_view)


# -----------------------------
# 页面入口
# -----------------------------

def _format_metric_value(row) -> str:
    if row["评选指标"] == "总达标率":
        return f"{float(row['指标值']):.1f}%"
    if row["评选指标"] == "有效运动次数":
        return format_goal_credit(row["指标值"])
    return str(row["指标值"])


def selection_page():
    st.subheader("运动评选")

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取记录失败。")
        st.exception(e)
        return

    today = get_now_local().date()

    available = _available_months(df_all, today)
    selected_months = st.multiselect(
        "选择用于评选统计的月份",
        options=available,
        default=_default_months(available, today),
        format_func=_month_label,
        help="勾选一个或多个自然月。下面的总时长、总次数、总达标率排名都会按所选月份重算。",
        key="selection_selected_months",
    )
    if not selected_months:
        st.warning("请至少选择一个月份。")
        return

    data = make_selection_tables(df_all, today, selected_months)
    summary = data["summary"]

    st.caption(
        f"当前统计月份：{'、'.join(_month_label(m) for m in data['selected_months'])}。"
        f"达标规则：{get_monthly_target_rule_text()}，"
        f"每次不少于 {data['target_minutes']} 分钟。"
    )

    def _top_three(metric_col: str, rank_col: str) -> pd.DataFrame:
        cols = list(
            dict.fromkeys(
                c
                for c in [
                    "姓名", metric_col, rank_col, "总运动时长", "有效运动次数",
                    "总运动次数", "总达标率", "达标月份数", "统计月份数",
                ]
                if c in summary.columns
            )
        )
        out = (
            summary[summary[rank_col] <= 3]
            .sort_values([rank_col, metric_col], ascending=[True, False])
            .loc[:, cols]
            .copy()
        )
        if "有效运动次数" in out.columns:
            out["有效运动次数"] = out["有效运动次数"].apply(format_goal_credit)
        if "总达标率" in out.columns:
            out["总达标率"] = out["总达标率"].map(lambda x: f"{float(x):.1f}%")
        return out

    st.markdown("#### 三项排名")
    c1, c2, c3 = st.columns(3)
    for col, (title, metric, rank) in zip(
        [c1, c2, c3],
        [
            ("总运动时长前三", "总运动时长", "总时长排名"),
            ("有效运动次数前三", "有效运动次数", "有效次数排名"),
            ("总达标率前三", "总达标率", "达标率排名"),
        ],
    ):
        with col:
            st.markdown(f"##### {title}")
            top = _top_three(metric, rank)
            if top.empty:
                st.info("暂无候选。")
            else:
                render_blue_table(top)

    st.divider()

    st.markdown("#### 运动多样性排行榜")
    st.caption(
        "按所选月份内不同运动类型数量排序。"
        "一次打卡如果选择多个运动类型，会分别计入多样性统计。"
    )
    diversity_board = data["diversity_board"]
    if diversity_board.empty:
        st.info("当前还没有可展示的运动多样性数据。")
    else:
        dv = diversity_board.copy()
        dv["有效运动次数"] = dv["有效运动次数"].apply(format_goal_credit)
        dv["总达标率"] = dv["总达标率"].map(lambda x: f"{float(x):.1f}%")
        render_blue_table(dv)

    st.divider()

    tab1, tab_honor, tab2, tab3 = st.tabs(
        ["候选汇总", "历史荣誉墙", "满勤 / 进步展示", "月度明细"]
    )

    with tab1:
        st.caption(
            "三项评选涉及总运动时长、有效运动次数、总达标率。"
            "同一成员如进入多个项目，最终建议人工确认。"
        )

        st.markdown("#### 按三项指标分别入围")
        candidates = data["selected_candidates"]
        if candidates.empty:
            st.info("当前还没有入围候选。")
        else:
            cv = candidates.copy()
            cv["指标值"] = cv.apply(_format_metric_value, axis=1)
            render_blue_table(cv)

        st.markdown("#### 每人推荐入围项")
        recommended = data["recommended_items"]
        if recommended.empty:
            st.info("当前还没有可参考的入围项。")
        else:
            rv = recommended.copy()
            rv["指标值"] = rv.apply(_format_metric_value, axis=1)
            render_blue_table(rv)

        with st.expander("完整评选指标表"):
            sv = summary.copy()
            sv["有效运动次数"] = sv["有效运动次数"].apply(format_goal_credit)
            sv["半次运动计入次数"] = sv["半次运动计入次数"].apply(format_goal_credit)
            sv["有效次数完成率"] = sv["有效次数完成率"].map(lambda x: f"{float(x):.1f}%")
            sv["总达标率"] = sv["总达标率"].map(lambda x: f"{float(x):.1f}%")
            sv["满勤候选"] = sv["满勤候选"].map({True: "是", False: "否"})
            sv["进步展示资格"] = sv["进步展示资格"].map({True: "是", False: "否"})
            render_blue_table(sv)
            st.download_button(
                "导出当前评选指标 CSV",
                data=sv.to_csv(index=False).encode("utf-8-sig"),
                file_name="selection_metrics_selected_months.csv",
                mime="text/csv",
            )

    with tab_honor:
        st.markdown("#### 历史荣誉墙")
        render_monthly_honor_wall(df_all, today)

    with tab2:
        left, right = st.columns(2)
        with left:
            st.markdown("#### 满勤候选")
            fa = data["full_attendance"]
            if fa.empty:
                st.info("当前没有总达标率 100% 的成员。")
            else:
                view = fa[["姓名", "达标月份数", "统计月份数", "总达标率"]].copy()
                view["总达标率"] = view["总达标率"].map(lambda x: f"{float(x):.1f}%")
                render_blue_table(view)
        with right:
            st.markdown("#### 进步展示资格")
            st.caption("达标率 50% 以上的成员可进入进步展示候选范围。")
            pe = data["progress_eligible"]
            if pe.empty:
                st.info("当前还没有成员达到 50% 资格线。")
            else:
                view = pe[["姓名", "达标月份数", "统计月份数", "总达标率"]].copy()
                view["总达标率"] = view["总达标率"].map(lambda x: f"{float(x):.1f}%")
                render_blue_table(view)

    with tab3:
        st.caption("每个人在所选月份里的逐月达标情况。")
        render_blue_table(data["monthly_detail"])
        st.download_button(
            "导出月度明细 CSV",
            data=data["monthly_detail"].to_csv(index=False).encode("utf-8-sig"),
            file_name="selection_monthly_detail_selected_months.csv",
            mime="text/csv",
        )

    st.divider()

    with st.expander("记录统计参考"):
        record_keeper = st.secrets.get("SELECTION_RECORD_KEEPER", "未设置")
        below_50 = data["below_50"]
        st.caption("这里仅用于内部记录统计参考，不参与上面的主要排名。")
        i1, i2 = st.columns(2)
        with i1:
            st.metric("记录统计负责人", record_keeper)
        with i2:
            st.metric("低于 50% 人数", f"{len(below_50)} 人")
        if below_50.empty:
            st.write("所选月份内没有低于 50% 达标率的成员。")
        else:
            view = below_50[["姓名", "达标月份数", "统计月份数", "总达标率"]].copy()
            view["总达标率"] = view["总达标率"].map(lambda x: f"{float(x):.1f}%")
            render_blue_table(view)

    st.divider()
    render_selection_heatmaps(data["monthly_heatmap_detail"])
