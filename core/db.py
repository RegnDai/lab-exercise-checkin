"""数据访问层：Supabase 客户端、读缓存、签名链接缓存、写操作。"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client

from core.config import APP_TIMEZONE, BACKFILL_GRACE_DAYS, BUCKET_NAME


@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_ROLE_KEY"],
    )


def get_now_local():
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def get_week_range(today):
    week_start = today - timedelta(days=today.weekday())
    return week_start, week_start + timedelta(days=6)


def get_month_range(today):
    month_start = today.replace(day=1)
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
    return month_start, next_month - timedelta(days=1)


def filter_by_date_range(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    if df.empty:
        return df
    return df[
        (df["activity_date"] >= start_date) & (df["activity_date"] <= end_date)
    ].copy()


# -----------------------------
# 打卡记录
# -----------------------------

@st.cache_data(ttl=60)
def load_checkins() -> pd.DataFrame:
    """读取全部打卡记录，缓存 60 秒；提交/修改后调用 load_checkins.clear()。"""
    supabase = get_supabase()
    response = (
        supabase.table("exercise_checkins")
        .select("*")
        .order("activity_date", desc=False)
        .limit(10000)
        .execute()
    )
    df = pd.DataFrame(response.data)
    if df.empty:
        return df

    df["activity_date"] = pd.to_datetime(df["activity_date"]).dt.date
    df["submitted_at"] = pd.to_datetime(df["submitted_at"], errors="coerce")
    df["duration_min"] = (
        pd.to_numeric(df["duration_min"], errors="coerce").fillna(0).astype(int)
    )
    if "mood_key" not in df.columns:
        df["mood_key"] = None

    # 补卡标记：提交日期比运动日期晚 N 天以上
    submitted_date = df["submitted_at"].dt.date
    gap = (
        pd.to_datetime(submitted_date, errors="coerce")
        - pd.to_datetime(df["activity_date"], errors="coerce")
    ).dt.days
    df["is_backfill"] = gap.fillna(0) > BACKFILL_GRACE_DAYS

    return df


def insert_checkin(row: dict):
    get_supabase().table("exercise_checkins").insert(row).execute()
    load_checkins.clear()


def update_checkin(record_id: int, update_row: dict):
    get_supabase().table("exercise_checkins").update(update_row).eq(
        "id", record_id
    ).execute()
    load_checkins.clear()


def delete_checkins(ids: list[int], file_paths: list[str]):
    supabase = get_supabase()
    if file_paths:
        supabase.storage.from_(BUCKET_NAME).remove(file_paths)
    if ids:
        supabase.table("exercise_checkins").delete().in_("id", ids).execute()
    load_checkins.clear()


# -----------------------------
# 图片签名链接（缓存 30 分钟，解决相册频繁调用 Storage API 的性能问题）
# -----------------------------

@st.cache_data(ttl=1800, show_spinner=False)
def create_signed_image_url(file_path: str, expires_in_seconds: int = 3600):
    if not str(file_path or "").strip():
        return None

    response = (
        get_supabase()
        .storage.from_(BUCKET_NAME)
        .create_signed_url(file_path, expires_in_seconds)
    )

    if isinstance(response, dict):
        return (
            response.get("signedURL")
            or response.get("signedUrl")
            or response.get("signed_url")
        )
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return (
            data.get("signedURL")
            or data.get("signedUrl")
            or data.get("signed_url")
        )
    return None


# -----------------------------
# 留言互动
# -----------------------------

@st.cache_data(ttl=10)
def load_message_reactions() -> pd.DataFrame:
    response = get_supabase().table("message_reactions").select("*").execute()
    df = pd.DataFrame(response.data if response and response.data else [])
    if df.empty:
        return pd.DataFrame(columns=["checkin_id", "emoji_key", "reaction_count"])

    df["checkin_id"] = (
        pd.to_numeric(df["checkin_id"], errors="coerce").fillna(0).astype(int)
    )
    df["emoji_key"] = df["emoji_key"].fillna("").astype(str)
    df["reaction_count"] = (
        pd.to_numeric(df["reaction_count"], errors="coerce").fillna(0).astype(int)
    )
    return df


def get_reaction_count_map() -> dict[tuple[int, str], int]:
    reactions = load_message_reactions()
    if reactions.empty:
        return {}
    return {
        (int(r["checkin_id"]), str(r["emoji_key"])): int(r["reaction_count"])
        for _, r in reactions.iterrows()
    }


def increment_reaction(checkin_id: int, emoji_key: str):
    get_supabase().rpc(
        "increment_message_reaction",
        {"p_checkin_id": int(checkin_id), "p_emoji_key": str(emoji_key)},
    ).execute()
    load_message_reactions.clear()


# -----------------------------
# 监督记录（新增，闭环随机抽查）
# 需要建表：见 README.md 中的 SQL
# -----------------------------

@st.cache_data(ttl=30)
def load_audit_logs() -> pd.DataFrame:
    try:
        response = (
            get_supabase()
            .table("audit_logs")
            .select("*")
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        return pd.DataFrame(response.data if response and response.data else [])
    except Exception:
        # 表还没建时静默降级，监督页会提示
        return pd.DataFrame()


def insert_audit_log(checkin_id: int, auditor: str, result: str, note: str):
    get_supabase().table("audit_logs").insert(
        {
            "checkin_id": int(checkin_id),
            "auditor": str(auditor or "").strip() or None,
            "result": str(result),
            "note": str(note or "").strip() or None,
            "created_at": get_now_local().isoformat(),
        }
    ).execute()
    load_audit_logs.clear()
