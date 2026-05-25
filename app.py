import hmac
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client


st.set_page_config(
    page_title="实验室运动打卡",
    page_icon="🏃",
    layout="centered",
)


# -----------------------------
# Config
# -----------------------------

BUCKET_NAME = st.secrets.get("BUCKET_NAME", "checkin-images")
MAX_UPLOAD_MB = int(st.secrets.get("MAX_UPLOAD_MB", 3))
APP_TIMEZONE = st.secrets.get("APP_TIMEZONE", "Asia/Shanghai")


@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_ROLE_KEY"],
    )


supabase = get_supabase()


# -----------------------------
# Helpers
# -----------------------------

def safe_name(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "", text)
    return text[:50] or "unknown"


def check_password(input_value: str, secret_value: str) -> bool:
    return hmac.compare_digest(str(input_value), str(secret_value))


def get_now_local():
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def get_file_ext(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in [".jpg", ".jpeg", ".png", ".webp"]:
        return suffix
    return ".jpg"


def already_checked_in(name: str, activity_date) -> bool:
    response = (
        supabase.table("exercise_checkins")
        .select("id")
        .eq("name", name)
        .eq("activity_date", activity_date.isoformat())
        .limit(1)
        .execute()
    )
    return len(response.data) > 0


def upload_image(uploaded_file, name: str, activity_date) -> dict:
    file_bytes = uploaded_file.getvalue()
    file_size_mb = len(file_bytes) / 1024 / 1024

    if file_size_mb > MAX_UPLOAD_MB:
        raise ValueError(f"文件太大：{file_size_mb:.2f} MB。上限是 {MAX_UPLOAD_MB} MB。")

    ext = get_file_ext(uploaded_file.name)
    clean_name = safe_name(name)
    unique_id = uuid4().hex

    storage_path = f"{activity_date.isoformat()}/{clean_name}-{unique_id}{ext}"

    supabase.storage.from_(BUCKET_NAME).upload(
        path=storage_path,
        file=file_bytes,
        file_options={
            "content-type": uploaded_file.type or "application/octet-stream",
            "upsert": "false",
        },
    )

    return {
        "file_path": storage_path,
        "file_name": uploaded_file.name,
        "file_mime": uploaded_file.type,
        "file_size": len(file_bytes),
    }


def create_signed_image_url(file_path: str, expires_in_seconds: int = 3600):
    response = (
        supabase.storage
        .from_(BUCKET_NAME)
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
# Login gate
# -----------------------------

if "invite_ok" not in st.session_state:
    st.session_state.invite_ok = False

st.title("🏃 实验室运动打卡")

if not st.session_state.invite_ok:
    st.caption("请输入实验室邀请码后进入打卡页面。")

    invite_code = st.text_input("实验室邀请码", type="password")

    if st.button("进入"):
        if check_password(invite_code, st.secrets["INVITE_CODE"]):
            st.session_state.invite_ok = True
            st.rerun()
        else:
            st.error("邀请码不对。")

    st.stop()


# -----------------------------
# Main tabs
# -----------------------------

tab_submit, tab_board, tab_admin = st.tabs(["提交打卡", "排行榜", "管理员"])


# -----------------------------
# Submit tab
# -----------------------------

with tab_submit:
    st.subheader("提交今日运动")

    members = list(st.secrets.get("MEMBERS", []))

    with st.form("checkin_form", clear_on_submit=True):
        if members:
            name = st.selectbox("姓名", members)
        else:
            name = st.text_input("姓名")

        activity_date = st.date_input("运动日期", value=get_now_local().date())

        activity_type = st.selectbox(
            "运动类型",
            ["跑步", "健身", "羽毛球", "篮球", "游泳", "骑行", "散步", "其他"],
        )

        duration_min = st.number_input(
            "运动时长，分钟",
            min_value=1,
            max_value=600,
            value=30,
            step=5,
        )

        uploaded_file = st.file_uploader(
            f"上传运动截图/照片，最大 {MAX_UPLOAD_MB} MB",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=False,
        )

        note = st.text_area("备注，可选", placeholder="比如：操场 3 km / 健身房腿部训练 / 羽毛球 1 小时")

        submitted = st.form_submit_button("提交打卡")

    if submitted:
        name = name.strip()

        if not name:
            st.error("姓名不能为空。")
        elif uploaded_file is None:
            st.error("请上传截图或照片。")
        elif already_checked_in(name, activity_date):
            st.warning("你今天已经提交过一次了。")
        else:
            try:
                file_info = upload_image(uploaded_file, name, activity_date)

                row = {
                    "name": name,
                    "activity_date": activity_date.isoformat(),
                    "activity_type": activity_type,
                    "duration_min": int(duration_min),
                    "note": note.strip() or None,
                    "file_path": file_info["file_path"],
                    "file_name": file_info["file_name"],
                    "file_mime": file_info["file_mime"],
                    "file_size": file_info["file_size"],
                    "submitted_at": datetime.now().astimezone().isoformat(),
                }

                supabase.table("exercise_checkins").insert(row).execute()

                st.success("打卡成功！")

            except Exception as e:
                st.error("提交失败。")
                st.exception(e)


# -----------------------------
# Leaderboard tab
# -----------------------------

with tab_board:
    st.subheader("排行榜")

    try:
        response = (
            supabase.table("exercise_checkins")
            .select("name, activity_date, activity_type, duration_min, submitted_at")
            .order("activity_date", desc=True)
            .execute()
        )

        df = pd.DataFrame(response.data)

        if df.empty:
            st.info("还没有打卡记录。")
        else:
            df["activity_date"] = pd.to_datetime(df["activity_date"])

            leaderboard = (
                df.groupby("name", as_index=False)
                .agg(
                    打卡天数=("activity_date", "nunique"),
                    总运动分钟=("duration_min", "sum"),
                )
                .sort_values(["打卡天数", "总运动分钟"], ascending=False)
            )

            st.dataframe(leaderboard, use_container_width=True, hide_index=True)

            st.divider()
            st.caption("最近打卡记录")
            recent = df.sort_values("activity_date", ascending=False).head(20)
            st.dataframe(recent, use_container_width=True, hide_index=True)

    except Exception as e:
        st.error("读取排行榜失败。")
        st.exception(e)


# -----------------------------
# Admin tab
# -----------------------------

with tab_admin:
    st.subheader("管理员后台")

    admin_password = st.text_input("管理员密码", type="password")

    if not check_password(admin_password, st.secrets["ADMIN_PASSWORD"]):
        st.info("输入管理员密码后查看完整记录。")
        st.stop()

    try:
        response = (
            supabase.table("exercise_checkins")
            .select("*")
            .order("submitted_at", desc=True)
            .execute()
        )

        df = pd.DataFrame(response.data)

        if df.empty:
            st.info("还没有记录。")
            st.stop()

        st.dataframe(df, use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="下载 CSV",
            data=csv,
            file_name="exercise_checkins.csv",
            mime="text/csv",
        )

        st.divider()
        st.subheader("查看上传图片")

        options = [
            f"{row['id']} | {row['name']} | {row['activity_date']} | {row['activity_type']}"
            for _, row in df.iterrows()
        ]

        selected = st.selectbox("选择一条记录", options)
        selected_id = int(selected.split("|")[0].strip())

        selected_row = df[df["id"] == selected_id].iloc[0]
        signed_url = create_signed_image_url(selected_row["file_path"])

        if signed_url:
            st.image(signed_url, caption=selected_row["file_name"], use_container_width=True)
        else:
            st.warning("图片临时链接生成失败。")

    except Exception as e:
        st.error("管理员后台读取失败。")
        st.exception(e)