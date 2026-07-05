"""规则计算层：运动类型/心情解析、有效次数折算、月度达标。

这里全是纯函数（不碰 Streamlit UI、不碰数据库），方便单元测试。
改打卡规则时只改这一个文件。
"""
import re

import pandas as pd

from core.config import (
    ACTIVITY_TYPE_SEPARATOR,
    CUSTOM_MOOD_PREFIX,
    DEFAULT_HALF_CREDIT_ACTIVITY_TYPES,
    FEMALE_MONTHLY_TARGET_CHECKINS,
    HALF_CREDIT_GOAL_CREDIT,
    HALF_CREDIT_RECORD_CAP,
    MEMBER_GENDER_MAP,
    MONTHLY_TARGET_CHECKINS_PER_PERSON,
    MONTHLY_TARGET_MINUTES_PER_CHECKIN,
    MOOD_LOOKUP,
    MOOD_SEPARATOR,
    PRIMARY_ACTIVITY_SUFFIX,
    RAW_HALF_CREDIT_ACTIVITY_TYPES,
)

_SPLIT_PATTERN = re.compile(r"[、,，/／+＋;；|]+")
_MOOD_SPLIT_PATTERN = re.compile(r"[、,，;；|]+")


# -----------------------------
# 运动类型解析
# -----------------------------

def _strip_primary_marker(value: str) -> str:
    return str(value).replace(PRIMARY_ACTIVITY_SUFFIX, "").strip()


def split_activity_types(value) -> list[str]:
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            raw_items.extend(split_activity_types(item))
    else:
        text_value = str(value).strip()
        if not text_value:
            return []
        raw_items = _SPLIT_PATTERN.split(text_value)

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw_items:
        label = _strip_primary_marker(item)
        if label and label not in seen:
            cleaned.append(label)
            seen.add(label)
    return cleaned


def join_activity_types(values) -> str:
    return ACTIVITY_TYPE_SEPARATOR.join(split_activity_types(values))


def format_activity(value) -> str:
    """展示用：去掉历史遗留的（主要）标记。"""
    return str(value or "").replace(PRIMARY_ACTIVITY_SUFFIX, "")


# 半次运动类型：字符串配置在这里解析（修复旧版 NameError）
if isinstance(RAW_HALF_CREDIT_ACTIVITY_TYPES, str):
    HALF_CREDIT_ACTIVITY_TYPES = split_activity_types(RAW_HALF_CREDIT_ACTIVITY_TYPES)
else:
    HALF_CREDIT_ACTIVITY_TYPES = list(RAW_HALF_CREDIT_ACTIVITY_TYPES)

for _activity in DEFAULT_HALF_CREDIT_ACTIVITY_TYPES:
    if _activity not in HALF_CREDIT_ACTIVITY_TYPES:
        HALF_CREDIT_ACTIVITY_TYPES.append(_activity)


def is_half_credit_activity(value) -> bool:
    """整条记录的所有类型都是半次类型时，按半次计入。"""
    types = split_activity_types(value)
    return bool(types) and all(t in HALF_CREDIT_ACTIVITY_TYPES for t in types)


# -----------------------------
# 心情解析
# -----------------------------

def split_mood_keys(value) -> list[str]:
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass

    if isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            raw_items.extend(split_mood_keys(item))
    else:
        text_value = str(value).strip()
        if not text_value or text_value.lower() in ["nan", "none", "nat"]:
            return []
        raw_items = _MOOD_SPLIT_PATTERN.split(text_value)

    cleaned, seen = [], set()
    for item in raw_items:
        item = str(item).strip()
        if item and item.lower() not in ["nan", "none", "nat"] and item not in seen:
            cleaned.append(item)
            seen.add(item)
    return cleaned


def make_custom_mood_key(emoji_value, label_value) -> str:
    emoji_value = str(emoji_value or "").strip()
    label_value = str(label_value or "").strip()
    if not emoji_value or not label_value:
        return ""
    return f"{CUSTOM_MOOD_PREFIX}{emoji_value} {label_value}"


def join_mood_values(selected_mood_keys, custom_emoji="", custom_label="") -> str | None:
    values = split_mood_keys(selected_mood_keys)
    custom_key = make_custom_mood_key(custom_emoji, custom_label)
    if custom_key:
        values.append(custom_key)

    unique, seen = [], set()
    for v in values:
        if v and v not in seen:
            unique.append(v)
            seen.add(v)
    return MOOD_SEPARATOR.join(unique) if unique else None


def _format_one_mood_key(mood_key) -> str:
    mood_key = str(mood_key or "").strip()
    if not mood_key:
        return ""
    if mood_key.startswith(CUSTOM_MOOD_PREFIX):
        return mood_key.removeprefix(CUSTOM_MOOD_PREFIX).strip() or "未知的心情～"
    mood = MOOD_LOOKUP.get(mood_key)
    return f"{mood['emoji']} {mood['label']}" if mood else mood_key


def format_mood_key(mood_key) -> str:
    keys = split_mood_keys(mood_key)
    if not keys:
        return "未知的心情～"
    parts = [_format_one_mood_key(k) for k in keys if _format_one_mood_key(k)]
    return MOOD_SEPARATOR.join(parts) or "未知的心情～"


def _one_mood_emoji(mood_key) -> str:
    mood_key = str(mood_key or "").strip()
    if not mood_key:
        return ""
    if mood_key.startswith(CUSTOM_MOOD_PREFIX):
        text = mood_key.removeprefix(CUSTOM_MOOD_PREFIX).strip()
        return text.split()[0] if text else ""
    mood = MOOD_LOOKUP.get(mood_key)
    return mood["emoji"] if mood else ""


def mood_emoji(mood_key) -> str:
    emojis = []
    for key in split_mood_keys(mood_key):
        e = _one_mood_emoji(key)
        if e and e not in emojis:
            emojis.append(e)
    return "".join(emojis)


def activity_emoji(activity_type: str) -> str:
    types = split_activity_types(activity_type)
    if not types:
        return "💬"
    joined = "、".join(types)
    for keywords, emoji in [
        (["跑步", "爬坡", "爬楼", "椭圆机", "踏步机"], "🏃"),
        (["力量", "健身", "划船机"], "💪"),
        (["散步", "走够一万步", "徒步", "登山"], "🚶"),
        (["浮潜"], "🤿"),
        (["桨板"], "🏄"),
        (["游泳"], "🏊"),
        (["骑行"], "🚴"),
        (["瑜伽", "普拉提", "舞蹈", "健身操"], "🧘"),
        (["呼啦圈"], "⭕"),
        (["匹克球"], "🏓"),
        (["台球"], "🎱"),
        (["篮球", "足球", "排球", "羽毛球", "乒乓球", "网球"], "🏀"),
    ]:
        if any(k in joined for k in keywords):
            return emoji
    return "✨"


# -----------------------------
# 目标 / 有效次数
# -----------------------------

def get_monthly_goal_settings() -> tuple[int, int]:
    return MONTHLY_TARGET_CHECKINS_PER_PERSON, MONTHLY_TARGET_MINUTES_PER_CHECKIN


def get_member_monthly_target_checkins(name, default_target: int | None = None) -> int:
    if default_target is None:
        default_target = MONTHLY_TARGET_CHECKINS_PER_PERSON
    gender = str(MEMBER_GENDER_MAP.get(str(name).strip(), "")).strip()
    if gender == "女":
        return FEMALE_MONTHLY_TARGET_CHECKINS
    return int(default_target)


def get_monthly_target_rule_text() -> str:
    default_target = MONTHLY_TARGET_CHECKINS_PER_PERSON
    if default_target == FEMALE_MONTHLY_TARGET_CHECKINS:
        return f"每人每月 {default_target} 次"
    return (
        f"男生每月 {default_target} 次，"
        f"女生每月 {FEMALE_MONTHLY_TARGET_CHECKINS} 次"
    )


def format_goal_credit(value) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}".rstrip("0").rstrip(".")


def add_goal_credit_columns(df: pd.DataFrame, target_minutes: int) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        for col in [
            "is_duration_qualified", "is_half_credit_primary",
            "normal_goal_credit", "half_credit_goal_record",
        ]:
            out[col] = []
        return out

    out["is_duration_qualified"] = out["duration_min"] >= target_minutes
    out["is_half_credit_primary"] = out["activity_type"].apply(is_half_credit_activity)
    out["normal_goal_credit"] = (
        out["is_duration_qualified"] & ~out["is_half_credit_primary"]
    ).astype(float)
    out["half_credit_goal_record"] = (
        out["is_duration_qualified"] & out["is_half_credit_primary"]
    ).astype(int)
    return out


def summarize_goal_credits(
    df: pd.DataFrame,
    group_cols: list[str],
    target_minutes: int,
) -> pd.DataFrame:
    """核心折算规则：

    - 同一人同一天多条记录，最多计入 1 次有效运动；
    - 当天只有半次类型记录时，该天计 0.5（同天多条半次仍是 0.5）；
    - 半次记录全周期最多计入 HALF_CREDIT_RECORD_CAP 条。
    """
    columns = group_cols + [
        "总打卡次数", "总运动分钟", "有效运动次数",
        "半次运动达标记录数", "半次运动计入次数",
    ]
    if df.empty or "activity_date" not in df.columns:
        return pd.DataFrame(columns=columns)

    temp = add_goal_credit_columns(df, target_minutes)

    day_group_cols = list(group_cols)
    if "activity_date" not in day_group_cols:
        day_group_cols = day_group_cols + ["activity_date"]

    day_level = temp.groupby(day_group_cols, as_index=False).agg(
        总打卡次数=("id", "count"),
        总运动分钟=("duration_min", "sum"),
        普通达标记录数=("normal_goal_credit", "sum"),
        半次达标记录数原始=("half_credit_goal_record", "sum"),
    )

    day_level["普通有效次数"] = (day_level["普通达标记录数"] > 0).astype(float)
    day_level["半次运动达标记录数"] = (
        (day_level["普通达标记录数"] <= 0)
        & (day_level["半次达标记录数原始"] > 0)
    ).astype(int)

    grouped = day_level.groupby(group_cols, as_index=False).agg(
        总打卡次数=("总打卡次数", "sum"),
        总运动分钟=("总运动分钟", "sum"),
        普通有效次数=("普通有效次数", "sum"),
        半次运动达标记录数=("半次运动达标记录数", "sum"),
    )

    grouped["半次运动计入次数"] = (
        grouped["半次运动达标记录数"].clip(upper=HALF_CREDIT_RECORD_CAP)
        * HALF_CREDIT_GOAL_CREDIT
    )
    grouped["有效运动次数"] = grouped["普通有效次数"] + grouped["半次运动计入次数"]

    grouped["总打卡次数"] = grouped["总打卡次数"].astype(int)
    grouped["总运动分钟"] = grouped["总运动分钟"].astype(int)
    grouped["半次运动达标记录数"] = grouped["半次运动达标记录数"].astype(int)

    return grouped[columns]


def explode_activity_records(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["activity_type_list"] = out["activity_type"].apply(split_activity_types)
    out = out[out["activity_type_list"].map(len) > 0].copy()
    if out.empty:
        return out
    out["activity_type_count"] = out["activity_type_list"].map(len)
    out = out.explode("activity_type_list")
    out["activity_type"] = out["activity_type_list"]
    out["duration_share"] = out["duration_min"] / out["activity_type_count"]
    return out


# -----------------------------
# 连续 / 徽章
# -----------------------------

def longest_true_streak(values: list[bool]) -> int:
    longest = current = 0
    for v in values:
        current = current + 1 if v else 0
        longest = max(longest, current)
    return longest


def ending_true_streak(values: list[bool]) -> int:
    streak = 0
    for v in reversed(values):
        if not v:
            break
        streak += 1
    return streak


def compute_day_streak(dates: set, today) -> tuple[int, int]:
    """返回（当前连续天数, 历史最长连续天数）。

    当前连续：以今天或昨天为终点往前数（今天还没打卡不清零）。
    """
    if not dates:
        return 0, 0

    sorted_days = sorted(dates)
    longest = current = 1
    for prev, cur in zip(sorted_days, sorted_days[1:]):
        current = current + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, current)

    from datetime import timedelta

    anchor = today if today in dates else today - timedelta(days=1)
    now_streak = 0
    day = anchor
    while day in dates:
        now_streak += 1
        day -= timedelta(days=1)
    return now_streak, longest


BADGE_DEFS = [
    # (key, emoji, 名称, 说明)
    ("first", "🌱", "第一步", "完成第一次打卡"),
    ("streak7", "🔥", "七日不断", "连续打卡 7 天"),
    ("streak14", "🌋", "半月燃烧", "连续打卡 14 天"),
    ("variety5", "🎨", "多面手", "解锁 5 种运动类型"),
    ("variety10", "🦾", "全能选手", "解锁 10 种运动类型"),
    ("min1000", "⏱️", "千分钟俱乐部", "累计运动 1000 分钟"),
    ("min3000", "🏔️", "三千分钟", "累计运动 3000 分钟"),
    ("month_goal", "🏅", "月度达标", "任意自然月完成目标"),
    ("month_goal3", "👑", "三月连冠", "连续 3 个已结束月份达标"),
    ("early_bird", "🌅", "早鸟", "早上 8 点前提交过打卡"),
    ("night_owl", "🌙", "夜猫子", "晚上 10 点后提交过打卡"),
    ("checkin50", "💯", "五十次里程碑", "累计打卡 50 次"),
]


def compute_badges(
    df_person: pd.DataFrame,
    goal_history_person: pd.DataFrame,
    today,
) -> list[dict]:
    """返回每个徽章的 {key, emoji, name, desc, earned}。"""
    earned: set[str] = set()

    if not df_person.empty:
        earned.add("first")

        dates = set(df_person["activity_date"].dropna().tolist())
        _, longest = compute_day_streak(dates, today)
        if longest >= 7:
            earned.add("streak7")
        if longest >= 14:
            earned.add("streak14")

        exploded = explode_activity_records(df_person)
        variety = exploded["activity_type"].nunique() if not exploded.empty else 0
        if variety >= 5:
            earned.add("variety5")
        if variety >= 10:
            earned.add("variety10")

        total_min = int(df_person["duration_min"].sum())
        if total_min >= 1000:
            earned.add("min1000")
        if total_min >= 3000:
            earned.add("min3000")

        if len(df_person) >= 50:
            earned.add("checkin50")

        submitted = pd.to_datetime(df_person["submitted_at"], errors="coerce").dropna()
        if not submitted.empty:
            hours = submitted.dt.hour
            if (hours < 8).any():
                earned.add("early_bird")
            if (hours >= 22).any():
                earned.add("night_owl")

    if not goal_history_person.empty:
        current_month = str(pd.Period(today, freq="M"))
        finished = goal_history_person[goal_history_person["月份"] < current_month]
        status = finished.sort_values("月份")["是否达标"].tolist()
        if any(goal_history_person["是否达标"]):
            earned.add("month_goal")
        if longest_true_streak(status) >= 3:
            earned.add("month_goal3")

    return [
        {"key": k, "emoji": e, "name": n, "desc": d, "earned": k in earned}
        for k, e, n, d in BADGE_DEFS
    ]
