import hashlib
import unicodedata

import hmac
import re
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps
from supabase import create_client


st.set_page_config(
    page_title="实验室运动打卡",
    page_icon="🏃",
    layout="wide",
)


# -----------------------------
# Config
# -----------------------------

BUCKET_NAME = st.secrets.get("BUCKET_NAME", "checkin-images")
MAX_UPLOAD_MB = int(st.secrets.get("MAX_UPLOAD_MB", 3))
MAX_SOURCE_UPLOAD_MB = int(st.secrets.get("MAX_SOURCE_UPLOAD_MB", 15))
MAX_STORED_IMAGE_MB = float(st.secrets.get("MAX_STORED_IMAGE_MB", MAX_UPLOAD_MB))
IMAGE_COMPRESSION_ENABLED = str(
    st.secrets.get("IMAGE_COMPRESSION_ENABLED", "true")
).lower() not in ["0", "false", "no", "off"]
IMAGE_MAX_SIDE = int(st.secrets.get("IMAGE_MAX_SIDE", 1600))
IMAGE_JPEG_QUALITY = int(st.secrets.get("IMAGE_JPEG_QUALITY", 82))
APP_TIMEZONE = st.secrets.get("APP_TIMEZONE", "Asia/Shanghai")
MIN_SUBMIT_MINUTES = int(
    st.secrets.get(
        "MIN_SUBMIT_MINUTES",
        st.secrets.get("MONTHLY_TARGET_MINUTES_PER_CHECKIN", 30),
    )
)

ACTIVITY_TYPES = [
    "健身",
    "力量训练",
    "跑步",
    "爬坡",
    "游泳",
    "骑行",
    "康复训练",
    "散步",
    "羽毛球",
    "乒乓球",
    "徒步",
    "登山",
    "跳绳",
    "爬楼",
    "椭圆机",
    "划船机",
    "瑜伽",
    "普拉提",
    "篮球",
    "足球",
    "排球",
    "网球",
    "舞蹈",
    "健身操",
    "其他",
]


@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SERVICE_ROLE_KEY"],
    )


supabase = get_supabase()

# BEGIN app polish styles

def inject_app_style():
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1120px;
            padding-top: 2.2rem;
            padding-bottom: 3rem;
        }

        h1, h2, h3 {
            letter-spacing: -0.03em;
        }

        h1 {
            font-size: 2rem;
            margin-bottom: 0.35rem;
        }

        h3 {
            margin-top: 1.2rem;
        }

        [data-testid="stCaptionContainer"] {
            color: #6b7280;
        }

        div[data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(250,248,245,0.92));
            border: 1px solid rgba(120, 92, 65, 0.12);
            border-radius: 18px;
            padding: 0.85rem 1rem;
            box-shadow: 0 8px 22px rgba(55, 48, 40, 0.055);
        }

        div[data-testid="stMetricLabel"] p {
            font-size: 0.92rem;
            color: #6b7280;
        }

        div[data-testid="stMetricValue"] {
            font-size: 1.55rem;
            line-height: 1.2;
            letter-spacing: -0.02em;
            white-space: normal;
            word-break: keep-all;
        }

        .stButton > button,
        [data-testid="stFormSubmitButton"] button {
            border-radius: 999px;
            padding: 0.55rem 1.2rem;
            border: 1px solid rgba(120, 92, 65, 0.18);
        }

        div[data-testid="stExpander"] {
            border-radius: 16px;
            border: 1px solid rgba(120, 92, 65, 0.12);
            overflow: hidden;
        }

        div[data-testid="stDataFrame"] {
            border-radius: 16px;
            overflow: hidden;
        }

        hr {
            margin: 1.4rem 0;
        }

        .soft-note {
            color: #6b7280;
            font-size: 0.95rem;
            line-height: 1.8;
        }

        .section-kicker {
            color: #8a6a4f;
            font-size: 0.9rem;
            margin-bottom: -0.4rem;
        }

        @media (max-width: 640px) {
            .block-container {
                padding-left: 1rem;
                padding-right: 1rem;
                padding-top: 1.4rem;
            }

            div[data-testid="stMetricValue"] {
                font-size: 1.35rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

inject_app_style()

# END app polish styles



# -----------------------------
# Helpers
# -----------------------------

def safe_name(text: str) -> str:
    """
    Supabase Storage object key should stay ASCII-safe.
    Keep a readable ASCII slug when possible, and append a short hash
    so Chinese names or duplicate names still produce stable safe paths.
    """
    original = text.strip()

    # Convert accents to ASCII when possible
    normalized = unicodedata.normalize("NFKD", original)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

    # Replace spaces with underscores, remove unsafe chars
    slug = re.sub(r"\s+", "_", ascii_text)
    slug = re.sub(r"[^a-zA-Z0-9_-]", "", slug)
    slug = slug.strip("_-").lower()

    # Stable short hash from original name, supports Chinese safely
    name_hash = hashlib.sha1(original.encode("utf-8")).hexdigest()[:8]

    if slug:
        return f"{slug}-{name_hash}"[:60]

    return f"user-{name_hash}"


def check_password(input_value: str, secret_value: str) -> bool:
    return hmac.compare_digest(str(input_value), str(secret_value))


def get_now_local():
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def get_file_ext(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in [".jpg", ".jpeg", ".png", ".webp"]:
        return suffix
    return ".jpg"




def compress_image_for_storage(uploaded_file) -> dict:
    """
    Compress uploaded images before sending them to Supabase Storage.

    The stored object is JPEG by default:
    - longest side is capped by IMAGE_MAX_SIDE
    - quality is controlled by IMAGE_JPEG_QUALITY
    - transparent PNG/WebP backgrounds are flattened to white
    """
    original_bytes = uploaded_file.getvalue()
    original_size_mb = len(original_bytes) / 1024 / 1024

    if original_size_mb > MAX_SOURCE_UPLOAD_MB:
        raise ValueError(
            f"文件太大：{original_size_mb:.2f} MB。"
            f"原图上限是 {MAX_SOURCE_UPLOAD_MB} MB。"
        )

    if not IMAGE_COMPRESSION_ENABLED:
        stored_size_mb = original_size_mb

        if stored_size_mb > MAX_STORED_IMAGE_MB:
            raise ValueError(
                f"文件太大：{stored_size_mb:.2f} MB。"
                f"存储上限是 {MAX_STORED_IMAGE_MB:.1f} MB。"
            )

        return {
            "bytes": original_bytes,
            "ext": get_file_ext(uploaded_file.name),
            "mime": uploaded_file.type or "application/octet-stream",
            "size": len(original_bytes),
        }

    try:
        image = Image.open(BytesIO(original_bytes))
        image = ImageOps.exif_transpose(image)

        if IMAGE_MAX_SIDE > 0:
            resample = getattr(Image, "Resampling", Image).LANCZOS
            image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE), resample)

        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")

        output = BytesIO()
        quality = max(40, min(int(IMAGE_JPEG_QUALITY), 95))

        image.save(
            output,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )

        compressed_bytes = output.getvalue()
        stored_size_mb = len(compressed_bytes) / 1024 / 1024

        if stored_size_mb > MAX_STORED_IMAGE_MB:
            raise ValueError(
                f"压缩后仍然太大：{stored_size_mb:.2f} MB。"
                f"存储上限是 {MAX_STORED_IMAGE_MB:.1f} MB。"
                "可以降低 IMAGE_MAX_SIDE 或 IMAGE_JPEG_QUALITY。"
            )

        return {
            "bytes": compressed_bytes,
            "ext": ".jpg",
            "mime": "image/jpeg",
            "size": len(compressed_bytes),
        }

    except ValueError:
        raise
    except Exception as e:
        raise ValueError("图片压缩失败。请上传 JPG、PNG 或 WEBP 图片。") from e


def upload_image(uploaded_file, name: str, activity_date) -> dict:
    processed = compress_image_for_storage(uploaded_file)

    clean_name = safe_name(name)
    unique_id = uuid4().hex

    storage_path = (
        f"{activity_date.isoformat()}/"
        f"{clean_name}-{unique_id}{processed['ext']}"
    )

    supabase.storage.from_(BUCKET_NAME).upload(
        path=storage_path,
        file=processed["bytes"],
        file_options={
            "content-type": processed["mime"],
            "upsert": "false",
        },
    )

    return {
        "file_path": storage_path,
        "file_name": uploaded_file.name,
        "file_mime": processed["mime"],
        "file_size": processed["size"],
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


@st.cache_data(ttl=60)
def load_checkins() -> pd.DataFrame:
    """
    Load check-in records from Supabase.

    Cached for 60 seconds to reduce repeated database reads.
    Clear this cache after successful submission.
    """
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
        pd.to_numeric(df["duration_min"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    return df


def get_week_range(today):
    """Return Monday-Sunday range for the given date."""
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end

def get_month_range(today):
    """Return first-last day range for the natural month."""
    month_start = today.replace(day=1)

    if today.month == 12:
        next_month_start = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month_start = today.replace(month=today.month + 1, day=1)

    month_end = next_month_start - timedelta(days=1)

    return month_start, month_end

def filter_by_date_range(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    if df.empty:
        return df

    return df[
        (df["activity_date"] >= start_date)
        & (df["activity_date"] <= end_date)
    ].copy()


def make_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["姓名", "总运动分钟", "打卡天数", "运动种类数", "打卡次数", "平均每次分钟"]
        )

    out = (
        df.groupby("name", as_index=False)
        .agg(
            总运动分钟=("duration_min", "sum"),
            打卡天数=("activity_date", "nunique"),
            运动种类数=("activity_type", "nunique"),
            打卡次数=("id", "count"),
        )
    )

    out["平均每次分钟"] = (out["总运动分钟"] / out["打卡次数"]).round(1)
    out = out.rename(columns={"name": "姓名"})

    return out.sort_values(
        ["总运动分钟", "打卡天数", "运动种类数"],
        ascending=False,
    )


def make_activity_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["运动类型", "总运动分钟", "参与人数", "打卡次数"]
        )

    out = (
        df.groupby("activity_type", as_index=False)
        .agg(
            总运动分钟=("duration_min", "sum"),
            参与人数=("name", "nunique"),
            打卡次数=("id", "count"),
        )
        .rename(columns={"activity_type": "运动类型"})
        .sort_values(["总运动分钟", "参与人数", "打卡次数"], ascending=False)
    )

    return out


def make_diversity_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=["姓名", "运动种类数", "运动类型", "总运动分钟", "打卡天数"]
        )

    diversity = (
        df.groupby("name")
        .agg(
            运动种类数=("activity_type", "nunique"),
            总运动分钟=("duration_min", "sum"),
            打卡天数=("activity_date", "nunique"),
        )
        .reset_index()
    )

    activity_list = (
        df.groupby("name")["activity_type"]
        .apply(lambda x: "、".join(sorted(set(x))))
        .reset_index(name="运动类型")
    )

    out = diversity.merge(activity_list, on="name", how="left")
    out = out.rename(columns={"name": "姓名"})

    return out.sort_values(
        ["运动种类数", "总运动分钟", "打卡天数"],
        ascending=False,
    )


def make_daily_presence_table(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    members = list(st.secrets.get("MEMBERS", []))

    if not members:
        if df.empty:
            members = []
        else:
            members = sorted(df["name"].dropna().unique().tolist())

    date_index = pd.date_range(start_date, end_date).date

    if df.empty:
        presence = pd.DataFrame(index=date_index, columns=members).fillna("—")
        presence.index.name = "日期"
        return presence.reset_index()

    temp = df.copy()
    temp["has_checkin"] = "✅"

    pivot = (
        temp.pivot_table(
            index="activity_date",
            columns="name",
            values="has_checkin",
            aggfunc="first",
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

    daily = (
        df.groupby(["activity_date", "name"], as_index=False)
        .agg(duration_min=("duration_min", "sum"))
    )

    pivot = (
        daily.pivot_table(
            index="activity_date",
            columns="name",
            values="duration_min",
            aggfunc="sum",
        )
        .reindex(date_index)
        .fillna(0)
    )

    cumulative = pivot.cumsum()
    cumulative.index = pd.to_datetime(cumulative.index)

    return cumulative


def format_date_range(start_date, end_date) -> str:
    return f"{start_date} 至 {end_date}"


def get_active_members() -> list[str]:
    """
    Members who are counted in the monthly lab goal.

    ACTIVE_MEMBERS is preferred because MEMBERS may include people who are not
    currently participating in this month's goal.
    """
    active_members = list(st.secrets.get("ACTIVE_MEMBERS", []))

    if active_members:
        return active_members

    return list(st.secrets.get("MEMBERS", []))


def make_energy_pool_stats(df_month: pd.DataFrame) -> dict:
    active_members = get_active_members()

    target_checkins_per_person = int(
        st.secrets.get("MONTHLY_TARGET_CHECKINS_PER_PERSON", 8)
    )
    target_minutes_per_checkin = int(
        st.secrets.get("MONTHLY_TARGET_MINUTES_PER_CHECKIN", 30)
    )
    energy_credit_cap_min = int(
        st.secrets.get("ENERGY_CREDIT_CAP_MIN", target_minutes_per_checkin)
    )

    member_count = len(active_members)

    target_checkins = member_count * target_checkins_per_person
    target_energy_minutes = target_checkins * target_minutes_per_checkin

    if df_month.empty or member_count == 0:
        return {
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

    df_goal = df_month[df_month["name"].isin(active_members)].copy()

    if df_goal.empty:
        actual_checkins = 0
        actual_energy_minutes = 0
        actual_total_minutes = 0
        participant_count = 0
    else:
        # A long workout is still recorded in the dashboard,
        # but only capped minutes count toward the shared energy pool.
        df_goal["energy_credit"] = df_goal["duration_min"].clip(
            upper=energy_credit_cap_min
        )

        actual_checkins = int(len(df_goal))
        actual_energy_minutes = int(df_goal["energy_credit"].sum())
        actual_total_minutes = int(df_goal["duration_min"].sum())
        participant_count = int(df_goal["name"].nunique())

    progress = (
        actual_energy_minutes / target_energy_minutes
        if target_energy_minutes > 0
        else 0
    )

    remaining_minutes = max(target_energy_minutes - actual_energy_minutes, 0)
    remaining_checkins_equivalent = (
        remaining_minutes / target_minutes_per_checkin
        if target_minutes_per_checkin > 0
        else 0
    )

    return {
        "active_members": active_members,
        "member_count": member_count,
        "target_checkins": target_checkins,
        "target_energy_minutes": target_energy_minutes,
        "actual_checkins": actual_checkins,
        "actual_energy_minutes": actual_energy_minutes,
        "actual_total_minutes": actual_total_minutes,
        "participant_count": participant_count,
        "progress": min(progress, 1.0),
        "remaining_minutes": remaining_minutes,
        "remaining_checkins_equivalent": remaining_checkins_equivalent,
        "df_goal": df_goal,
    }


def make_energy_pool_contribution_table(df_goal: pd.DataFrame) -> pd.DataFrame:
    active_members = get_active_members()

    if df_goal.empty:
        return pd.DataFrame({
            "姓名": active_members,
            "能量贡献": [0] * len(active_members),
            "实际运动分钟": [0] * len(active_members),
            "打卡次数": [0] * len(active_members),
        })

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

    out = (
        all_members.merge(out, on="姓名", how="left")
        .fillna({
            "能量贡献": 0,
            "实际运动分钟": 0,
            "打卡次数": 0,
        })
    )

    out["能量贡献"] = out["能量贡献"].astype(int)
    out["实际运动分钟"] = out["实际运动分钟"].astype(int)
    out["打卡次数"] = out["打卡次数"].astype(int)

    return out.sort_values(
        ["能量贡献", "打卡次数", "实际运动分钟"],
        ascending=False,
    )




def render_energy_bowl(progress: float):
    """
    Render a bowl-style progress visualization.

    progress: 0~1
    """
    progress = max(0.0, min(1.0, float(progress)))
    percent = progress * 100

    st.markdown(
        f"""
        <style>
        .energy-bowl-wrap {{
            display: flex;
            justify-content: center;
            margin: 0.75rem 0 1.35rem 0;
        }}

        .energy-bowl-card {{
            width: 100%;
            max-width: 440px;
            text-align: center;
        }}

        .energy-bowl {{
            position: relative;
            margin: 0 auto;
            width: 330px;
            height: 205px;
            border: 9px solid #7a5639;
            border-top: 0;
            border-radius: 0 0 170px 170px / 0 0 125px 125px;
            background: linear-gradient(180deg, #fffaf4 0%, #f7eee4 100%);
            overflow: hidden;
            box-shadow:
                inset 0 0 0 2px rgba(255,255,255,0.72),
                0 14px 32px rgba(54, 43, 32, 0.12);
        }}

        .energy-bowl::before {{
            content: "";
            position: absolute;
            left: 18px;
            right: 18px;
            top: 0;
            height: 18px;
            border-radius: 50%;
            background: rgba(255,255,255,0.42);
            z-index: 2;
        }}

        .energy-liquid {{
            position: absolute;
            left: 0;
            right: 0;
            bottom: 0;
            height: {percent:.1f}%;
            background:
                radial-gradient(circle at 30% 18%, rgba(255,255,255,0.32), transparent 22%),
                linear-gradient(180deg, #f6bd60 0%, #f28444 46%, #d95d39 100%);
            border-radius: 0 0 150px 150px / 0 0 110px 110px;
            transition: height 0.6s ease;
        }}

        .energy-liquid::before {{
            content: "";
            position: absolute;
            top: -13px;
            left: 0;
            width: 100%;
            height: 25px;
            background: rgba(255, 230, 185, 0.55);
            border-radius: 50%;
        }}

        .energy-bowl-shine {{
            position: absolute;
            top: 25px;
            left: 38px;
            width: 34px;
            height: 112px;
            background: rgba(255,255,255,0.24);
            border-radius: 999px;
            transform: rotate(10deg);
            z-index: 2;
        }}

        .energy-bowl-label {{
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 3;
            pointer-events: none;
        }}

        .energy-bowl-percent {{
            font-size: 2.35rem;
            font-weight: 800;
            color: #3f3027;
            line-height: 1.1;
            text-shadow: 0 1px 8px rgba(255,255,255,0.62);
        }}

        .energy-bowl-text {{
            margin-top: 0.3rem;
            font-size: 0.98rem;
            color: #6a4a3c;
            text-shadow: 0 1px 8px rgba(255,255,255,0.62);
        }}

        .energy-bowl-caption {{
            margin-top: 0.8rem;
            font-size: 0.95rem;
            color: #6b7280;
        }}

        @media (max-width: 640px) {{
            .energy-bowl {{
                width: 260px;
                height: 165px;
            }}

            .energy-bowl-percent {{
                font-size: 2rem;
            }}

            .energy-bowl-text {{
                font-size: 0.92rem;
            }}
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
            <div class="energy-bowl-caption">
              一点一点，碗就满了。
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# BEGIN monthly goal helpers

def get_monthly_goal_settings() -> tuple[int, int]:
    """
    Monthly goal rule.

    Default:
    - 7 qualifying sessions per month
    - each qualifying session must be >= 30 minutes
    """
    target_checkins = int(st.secrets.get("MONTHLY_TARGET_CHECKINS_PER_PERSON", 8))
    target_minutes = int(st.secrets.get("MONTHLY_TARGET_MINUTES_PER_CHECKIN", 30))
    return target_checkins, target_minutes


def make_current_month_goal_table(df_month_to_date: pd.DataFrame) -> pd.DataFrame:
    """
    Current-month goal status by person.

    A qualifying session means duration_min >= target_minutes.
    One long workout still counts as one qualifying session, not multiple.
    """
    active_members = get_active_members()
    target_checkins, target_minutes = get_monthly_goal_settings()

    base = pd.DataFrame({"姓名": active_members})

    if not active_members:
        return pd.DataFrame(
            columns=[
                "姓名",
                "有效运动次数",
                "总打卡次数",
                "总运动分钟",
                "达标进度",
                "还差有效运动次数",
                "本月状态",
                "达标提示",
            ]
        )

    if df_month_to_date.empty:
        out = base.copy()
        out["有效运动次数"] = 0
        out["总打卡次数"] = 0
        out["总运动分钟"] = 0
    else:
        df = df_month_to_date[df_month_to_date["name"].isin(active_members)].copy()
        df["is_qualified"] = df["duration_min"] >= target_minutes

        summary = (
            df.groupby("name", as_index=False)
            .agg(
                有效运动次数=("is_qualified", "sum"),
                总打卡次数=("id", "count"),
                总运动分钟=("duration_min", "sum"),
            )
            .rename(columns={"name": "姓名"})
        )

        out = base.merge(summary, on="姓名", how="left").fillna(
            {
                "有效运动次数": 0,
                "总打卡次数": 0,
                "总运动分钟": 0,
            }
        )

    out["有效运动次数"] = out["有效运动次数"].astype(int)
    out["总打卡次数"] = out["总打卡次数"].astype(int)
    out["总运动分钟"] = out["总运动分钟"].astype(int)

    out["还差有效运动次数"] = (
        target_checkins - out["有效运动次数"]
    ).clip(lower=0)

    out["达标进度"] = out["有效运动次数"].astype(str) + f"/{target_checkins}"

    out["本月状态"] = out["还差有效运动次数"].apply(
        lambda x: "✅ 已达标" if x == 0 else "未达标"
    )

    out["达标提示"] = out["还差有效运动次数"].apply(
        lambda x: "本月已达标" if x == 0 else f"还差 {int(x)} 次有效运动"
    )

    return out.sort_values(
        ["有效运动次数", "总运动分钟", "总打卡次数"],
        ascending=False,
    )


def make_monthly_goal_history(df_all: pd.DataFrame, today) -> pd.DataFrame:
    """
    Person-month goal history.

    Missing person-month records are treated as zero qualifying sessions.
    """
    active_members = get_active_members()
    target_checkins, target_minutes = get_monthly_goal_settings()

    columns = [
        "姓名",
        "月份",
        "有效运动次数",
        "总打卡次数",
        "总运动分钟",
        "是否达标",
        "还差有效运动次数",
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
        [active_members, months],
        names=["姓名", "月份"],
    ).to_frame(index=False)

    if df_all.empty:
        summary = pd.DataFrame(
            columns=["姓名", "月份", "有效运动次数", "总打卡次数", "总运动分钟"]
        )
    else:
        df = df_all[df_all["name"].isin(active_members)].copy()
        df["月份"] = pd.to_datetime(df["activity_date"]).dt.to_period("M")
        df["is_qualified"] = df["duration_min"] >= target_minutes

        summary = (
            df.groupby(["name", "月份"], as_index=False)
            .agg(
                有效运动次数=("is_qualified", "sum"),
                总打卡次数=("id", "count"),
                总运动分钟=("duration_min", "sum"),
            )
            .rename(columns={"name": "姓名"})
        )

    out = skeleton.merge(summary, on=["姓名", "月份"], how="left").fillna(
        {
            "有效运动次数": 0,
            "总打卡次数": 0,
            "总运动分钟": 0,
        }
    )

    out["有效运动次数"] = out["有效运动次数"].astype(int)
    out["总打卡次数"] = out["总打卡次数"].astype(int)
    out["总运动分钟"] = out["总运动分钟"].astype(int)

    out["是否达标"] = out["有效运动次数"] >= target_checkins
    out["还差有效运动次数"] = (
        target_checkins - out["有效运动次数"]
    ).clip(lower=0)
    out["月份"] = out["月份"].astype(str)

    return out


def _longest_true_streak(values: list[bool]) -> int:
    longest = 0
    current = 0

    for value in values:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    return longest


def _ending_true_streak(values: list[bool]) -> int:
    streak = 0

    for value in reversed(values):
        if value:
            streak += 1
        else:
            break

    return streak


def make_goal_streak_table(goal_history: pd.DataFrame, today) -> pd.DataFrame:
    """
    Cumulative and streak goal summary by person.

    Consecutive goal streak is calculated using completed months only.
    The current unfinished month does not break a streak.
    """
    active_members = get_active_members()
    target_checkins, _ = get_monthly_goal_settings()
    current_month = str(pd.Period(today, freq="M"))

    columns = [
        "姓名",
        "累计达标月数",
        "统计月数",
        "累计达标率",
        "历史连续达标月数",
        "最长连续达标月数",
        "本月有效运动次数",
        "本月还差有效运动次数",
        "本月状态",
        "本月提示",
    ]

    if goal_history.empty:
        return pd.DataFrame(columns=columns)

    rows = []

    for name in active_members:
        person = goal_history[goal_history["姓名"] == name].sort_values("月份")

        completed = person[person["月份"] < current_month]
        completed_status = completed["是否达标"].tolist()

        current_row = person[person["月份"] == current_month]

        if current_row.empty:
            current_valid = 0
            current_remaining = target_checkins
            current_achieved = False
        else:
            current_valid = int(current_row.iloc[0]["有效运动次数"])
            current_remaining = int(current_row.iloc[0]["还差有效运动次数"])
            current_achieved = bool(current_row.iloc[0]["是否达标"])

        total_months = len(person)
        achieved_months = int(person["是否达标"].sum())
        achievement_rate = (
            achieved_months / total_months * 100
            if total_months > 0
            else 0
        )

        rows.append(
            {
                "姓名": name,
                "累计达标月数": achieved_months,
                "统计月数": total_months,
                "累计达标率": f"{achievement_rate:.1f}%",
                "历史连续达标月数": _ending_true_streak(completed_status),
                "最长连续达标月数": _longest_true_streak(completed_status),
                "本月有效运动次数": current_valid,
                "本月还差有效运动次数": current_remaining,
                "本月状态": "✅ 已达标" if current_achieved else "未达标",
                "本月提示": "本月已达标" if current_remaining == 0 else f"还差 {current_remaining} 次有效运动",
            }
        )

    out = pd.DataFrame(rows)

    return out.sort_values(
        [
            "累计达标月数",
            "历史连续达标月数",
            "最长连续达标月数",
            "本月有效运动次数",
        ],
        ascending=False,
    )

# END monthly goal helpers


# -----------------------------
# Login gate
# -----------------------------

if "invite_ok" not in st.session_state:
    st.session_state.invite_ok = False

st.title("实验室运动记录")

if not st.session_state.invite_ok:
    st.caption("输入邀请码进入。")

    invite_code = st.text_input("邀请码", type="password")

    if st.button("进入打卡"):
        if check_password(invite_code, st.secrets["INVITE_CODE"]):
            st.session_state.invite_ok = True
            st.rerun()
        else:
            st.error("邀请码不对。")

    st.stop()


# -----------------------------
# Main tabs
# -----------------------------

tab_submit, tab_dashboard, tab_goal, tab_selection, tab_gallery, tab_admin = st.tabs(["打卡", "总览", "本月目标", "评选", "相册", "后台"])


# -----------------------------
# Submit tab
# -----------------------------

with tab_submit:
    st.subheader("今天运动了么？")

    members = list(st.secrets.get("MEMBERS", []))

    with st.form("checkin_form", clear_on_submit=True):
        if members:
            name = st.selectbox("姓名", members)
        else:
            name = st.text_input("姓名")

        activity_date = st.date_input("运动日期", value=get_now_local().date())

        activity_type = st.selectbox(
            "运动类型",
            ACTIVITY_TYPES,
        )

        duration_min = st.number_input(
            "运动时长（分钟）",
            min_value=MIN_SUBMIT_MINUTES,
            max_value=600,
            value=MIN_SUBMIT_MINUTES,
            step=5,
            help=f"每次提交至少 {MIN_SUBMIT_MINUTES} 分钟。",
        )

        uploaded_file = st.file_uploader(
            f"上传截图或照片（原图不超过 {MAX_SOURCE_UPLOAD_MB} MB，系统会自动压缩）",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=False,
        )

        note = st.text_area(
            "今天有什么想说的？",
            placeholder="记录一点今天的状态、心情、运动感受，或者随便写一句话。",
            )

        submitted = st.form_submit_button("提交打卡")

    if submitted:
        name = name.strip()

        if not name:
            st.error("姓名不能为空。")
        elif uploaded_file is None:
            st.error("请上传一张截图或照片。")
        elif int(duration_min) < MIN_SUBMIT_MINUTES:
            st.error(f"每次运动记录至少需要 {MIN_SUBMIT_MINUTES} 分钟。")
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

                load_checkins.clear()

                st.success("记录好了，辛苦！")

            except Exception as e:
                st.error("提交失败。")
                st.exception(e)




# -----------------------------
# Selection board helpers
# -----------------------------

def _selection_goal_settings() -> tuple[int, int]:
    target_checkins_per_person = int(
        st.secrets.get("MONTHLY_TARGET_CHECKINS_PER_PERSON", 8)
    )
    target_minutes_per_checkin = int(
        st.secrets.get("MONTHLY_TARGET_MINUTES_PER_CHECKIN", 30)
    )
    return target_checkins_per_person, target_minutes_per_checkin


def _selection_active_members(df_all: pd.DataFrame) -> list[str]:
    active_members = list(st.secrets.get("ACTIVE_MEMBERS", []))

    if active_members:
        return active_members

    members = list(st.secrets.get("MEMBERS", []))

    if members:
        return members

    if not df_all.empty and "name" in df_all.columns:
        return sorted(df_all["name"].dropna().astype(str).unique().tolist())

    return []


def _selection_available_months(df_all: pd.DataFrame, today) -> list[str]:
    months = set()

    if not df_all.empty and "activity_date" in df_all.columns:
        dates = pd.to_datetime(df_all["activity_date"], errors="coerce").dropna()

        if not dates.empty:
            months.update(dates.dt.to_period("M").astype(str).tolist())

    months.add(str(pd.Period(today, freq="M")))

    return sorted(months)


def _selection_default_months(available_months: list[str], today) -> list[str]:
    try:
        default_month_count = int(st.secrets.get("SELECTION_DEFAULT_MONTHS", 3))
    except Exception:
        default_month_count = 3

    default_month_count = max(1, min(default_month_count, 24))

    if not available_months:
        return [str(pd.Period(today, freq="M"))]

    return available_months[-default_month_count:]


def _selection_month_label(month_value: str) -> str:
    try:
        period = pd.Period(month_value, freq="M")
        return f"{period.year}年{period.month}月"
    except Exception:
        return str(month_value)


def make_selection_tables(
    df_all: pd.DataFrame,
    today,
    selected_months: list[str],
) -> dict:
    target_checkins, target_minutes = _selection_goal_settings()
    active_members = _selection_active_members(df_all)

    selected_months = sorted(set(str(x) for x in selected_months if str(x).strip()))

    if not selected_months:
        selected_months = [str(pd.Period(today, freq="M"))]

    if not df_all.empty:
        df_period = df_all.copy()
        df_period["activity_date"] = pd.to_datetime(
            df_period["activity_date"],
            errors="coerce",
        )
        df_period = df_period.dropna(subset=["activity_date"])
        df_period["selection_month"] = df_period["activity_date"].dt.to_period("M").astype(str)
        df_period = df_period[df_period["selection_month"].isin(selected_months)].copy()
    else:
        df_period = pd.DataFrame()

    if active_members and not df_period.empty:
        df_period = df_period[df_period["name"].isin(active_members)].copy()

    if active_members:
        base = pd.MultiIndex.from_product(
            [active_members, selected_months],
            names=["name", "month"],
        ).to_frame(index=False)
    else:
        base = pd.DataFrame(columns=["name", "month"])

    if df_period.empty:
        monthly = pd.DataFrame(
            columns=[
                "name",
                "month",
                "月运动次数",
                "月有效运动次数",
                "月运动时长",
            ]
        )
    else:
        temp = df_period.copy()
        temp["month"] = temp["selection_month"]
        temp["is_effective"] = temp["duration_min"] >= target_minutes

        monthly = (
            temp.groupby(["name", "month"], as_index=False)
            .agg(
                月运动次数=("id", "count"),
                月有效运动次数=("is_effective", "sum"),
                月运动时长=("duration_min", "sum"),
            )
        )

    monthly_grid = (
        base.merge(monthly, on=["name", "month"], how="left")
        .fillna(
            {
                "月运动次数": 0,
                "月有效运动次数": 0,
                "月运动时长": 0,
            }
        )
    )

    for col in ["月运动次数", "月有效运动次数", "月运动时长"]:
        monthly_grid[col] = monthly_grid[col].astype(int)

    monthly_grid["月度达标"] = monthly_grid["月有效运动次数"] >= target_checkins

    if monthly_grid.empty:
        person_month = pd.DataFrame(
            {
                "name": active_members,
                "达标月份数": [0] * len(active_members),
                "统计月份数": [len(selected_months)] * len(active_members),
            }
        )
    else:
        person_month = (
            monthly_grid.groupby("name", as_index=False)
            .agg(
                达标月份数=("月度达标", "sum"),
                统计月份数=("month", "nunique"),
            )
        )

    if df_period.empty:
        totals = pd.DataFrame(
            {
                "name": active_members,
                "总运动时长": [0] * len(active_members),
                "总运动次数": [0] * len(active_members),
                "有效运动次数": [0] * len(active_members),
            }
        )
    else:
        temp = df_period.copy()
        temp["is_effective"] = temp["duration_min"] >= target_minutes

        totals = (
            temp.groupby("name", as_index=False)
            .agg(
                总运动时长=("duration_min", "sum"),
                总运动次数=("id", "count"),
                有效运动次数=("is_effective", "sum"),
            )
        )

    members_df = pd.DataFrame({"name": active_members})

    summary = (
        members_df.merge(totals, on="name", how="left")
        .merge(person_month, on="name", how="left")
        .fillna(
            {
                "总运动时长": 0,
                "总运动次数": 0,
                "有效运动次数": 0,
                "达标月份数": 0,
                "统计月份数": len(selected_months),
            }
        )
    )

    for col in ["总运动时长", "总运动次数", "有效运动次数", "达标月份数", "统计月份数"]:
        summary[col] = summary[col].astype(int)

    summary["周期目标次数"] = summary["统计月份数"] * target_checkins

    summary["有效次数完成率"] = summary.apply(
        lambda row: (
            row["有效运动次数"] / row["周期目标次数"] * 100
            if row["周期目标次数"] > 0
            else 0
        ),
        axis=1,
    ).round(1)

    summary["总达标率"] = summary.apply(
        lambda row: (
            row["达标月份数"] / row["统计月份数"] * 100
            if row["统计月份数"] > 0
            else 0
        ),
        axis=1,
    ).round(1)

    summary["总时长排名"] = summary["总运动时长"].rank(
        method="min",
        ascending=False,
    ).astype(int)

    summary["总次数排名"] = summary["总运动次数"].rank(
        method="min",
        ascending=False,
    ).astype(int)

    summary["达标率排名"] = summary["总达标率"].rank(
        method="min",
        ascending=False,
    ).astype(int)

    summary["满勤候选"] = summary["总达标率"] >= 100
    summary["进步展示资格"] = summary["总达标率"] >= 50

    summary = summary.rename(columns={"name": "姓名"})

    summary = summary[
        [
            "姓名",
            "总运动时长",
            "总运动次数",
            "有效运动次数",
            "周期目标次数",
            "有效次数完成率",
            "达标月份数",
            "统计月份数",
            "总达标率",
            "总时长排名",
            "总次数排名",
            "达标率排名",
            "满勤候选",
            "进步展示资格",
        ]
    ].sort_values(
        ["总达标率", "总运动时长", "总运动次数"],
        ascending=False,
    )

    metric_specs = [
        ("总运动时长", "总运动时长", "总时长排名"),
        ("总运动次数", "总运动次数", "总次数排名"),
        ("总达标率", "总达标率", "达标率排名"),
    ]

    selection_frames = []

    for metric_name, value_col, rank_col in metric_specs:
        temp = summary.copy()
        temp = temp[(temp[rank_col] <= 3) & (temp[value_col] > 0)]

        if temp.empty:
            continue

        temp["评选指标"] = metric_name
        temp["指标值"] = temp[value_col]
        temp["名次"] = temp[rank_col]

        selection_frames.append(
            temp[
                [
                    "姓名",
                    "评选指标",
                    "指标值",
                    "名次",
                ]
            ]
        )

    if selection_frames:
        selected_candidates = pd.concat(selection_frames, ignore_index=True)

        recommended_items = (
            selected_candidates.sort_values(
                ["姓名", "名次"],
                ascending=[True, True],
            )
            .groupby("姓名", as_index=False)
            .first()
            .sort_values(["名次", "姓名"], ascending=[True, True])
        )
    else:
        selected_candidates = pd.DataFrame(
            columns=["姓名", "评选指标", "指标值", "名次"]
        )
        recommended_items = selected_candidates.copy()

    full_attendance = summary[summary["满勤候选"]].copy()
    progress_eligible = summary[summary["进步展示资格"]].copy()
    below_50 = summary[summary["总达标率"] < 50].copy()

    monthly_detail = monthly_grid.rename(
        columns={
            "name": "姓名",
            "month": "月份",
        }
    ).copy()

    if not monthly_detail.empty:
        monthly_detail["月份"] = monthly_detail["月份"].map(_selection_month_label)
        monthly_detail["月度达标"] = monthly_detail["月度达标"].map(
            {True: "是", False: "否"}
        )

    return {
        "summary": summary,
        "selected_candidates": selected_candidates,
        "recommended_items": recommended_items,
        "full_attendance": full_attendance,
        "progress_eligible": progress_eligible,
        "below_50": below_50,
        "monthly_detail": monthly_detail,
        "target_checkins": target_checkins,
        "target_minutes": target_minutes,
        "selected_months": selected_months,
    }


def render_selection_board(df_all: pd.DataFrame, today):
    available_months = _selection_available_months(df_all, today)
    default_months = _selection_default_months(available_months, today)

    selected_months = st.multiselect(
        "选择用于评选统计的月份",
        options=available_months,
        default=default_months,
        format_func=_selection_month_label,
        help="勾选一个或多个自然月。下面的总时长、总次数、总达标率排名都会按所选月份重算。",
        key="selection_selected_months",
    )

    if not selected_months:
        st.warning("请至少选择一个月份。")
        return

    data = make_selection_tables(df_all, today, selected_months)

    summary = data["summary"]
    selected_candidates = data["selected_candidates"]
    recommended_items = data["recommended_items"]
    full_attendance = data["full_attendance"]
    progress_eligible = data["progress_eligible"]
    below_50 = data["below_50"]
    monthly_detail = data["monthly_detail"]

    selected_label = "、".join(_selection_month_label(x) for x in data["selected_months"])

    st.caption(
        f"当前统计月份：{selected_label}。"
        f"达标规则：每月 {data['target_checkins']} 次，"
        f"每次不少于 {data['target_minutes']} 分钟。"
    )

    def _top_three(metric_col: str, rank_col: str) -> pd.DataFrame:
        cols = [
            "姓名",
            metric_col,
            rank_col,
            "总运动时长",
            "总运动次数",
            "总达标率",
            "达标月份数",
            "统计月份数",
        ]
        cols = list(dict.fromkeys([c for c in cols if c in summary.columns]))

        out = (
            summary[summary[rank_col] <= 3]
            .sort_values([rank_col, metric_col], ascending=[True, False])
            .loc[:, cols]
            .copy()
        )

        if "总达标率" in out.columns:
            out["总达标率"] = out["总达标率"].map(lambda x: f"{float(x):.1f}%")

        return out

    st.markdown("#### 三项排名")

    rank_col1, rank_col2, rank_col3 = st.columns(3)

    with rank_col1:
        st.markdown("##### 总运动时长前三")
        top_time = _top_three("总运动时长", "总时长排名")
        if top_time.empty:
            st.info("暂无候选。")
        else:
            st.dataframe(top_time, use_container_width=True, hide_index=True)

    with rank_col2:
        st.markdown("##### 总运动次数前三")
        top_count = _top_three("总运动次数", "总次数排名")
        if top_count.empty:
            st.info("暂无候选。")
        else:
            st.dataframe(top_count, use_container_width=True, hide_index=True)

    with rank_col3:
        st.markdown("##### 总达标率前三")
        top_rate = _top_three("总达标率", "达标率排名")
        if top_rate.empty:
            st.info("暂无候选。")
        else:
            st.dataframe(top_rate, use_container_width=True, hide_index=True)

    st.divider()

    selection_tab1, selection_tab2, selection_tab3 = st.tabs(
        ["候选汇总", "满勤 / 进步展示", "月度明细"]
    )

    with selection_tab1:
        st.caption(
            "三项评选涉及总运动时长、总运动次数、总达标率。"
            "同一成员如进入多个项目，最终建议人工确认。"
        )

        st.markdown("#### 按三项指标分别入围")
        if selected_candidates.empty:
            st.info("当前还没有入围候选。")
        else:
            candidate_view = selected_candidates.copy()
            candidate_view["指标值"] = candidate_view.apply(
                lambda row: f"{float(row['指标值']):.1f}%"
                if row["评选指标"] == "总达标率"
                else row["指标值"],
                axis=1,
            )
            st.dataframe(candidate_view, use_container_width=True, hide_index=True)

        st.markdown("#### 每人推荐入围项")
        if recommended_items.empty:
            st.info("当前还没有可参考的入围项。")
        else:
            recommended_view = recommended_items.copy()
            recommended_view["指标值"] = recommended_view.apply(
                lambda row: f"{float(row['指标值']):.1f}%"
                if row["评选指标"] == "总达标率"
                else row["指标值"],
                axis=1,
            )
            st.dataframe(recommended_view, use_container_width=True, hide_index=True)

        summary_view = summary.copy()
        summary_view["有效次数完成率"] = summary_view["有效次数完成率"].map(lambda x: f"{float(x):.1f}%")
        summary_view["总达标率"] = summary_view["总达标率"].map(lambda x: f"{float(x):.1f}%")
        summary_view["满勤候选"] = summary_view["满勤候选"].map({True: "是", False: "否"})
        summary_view["进步展示资格"] = summary_view["进步展示资格"].map({True: "是", False: "否"})

        with st.expander("完整评选指标表"):
            st.dataframe(summary_view, use_container_width=True, hide_index=True)

            st.download_button(
                label="导出当前评选指标 CSV",
                data=summary_view.to_csv(index=False).encode("utf-8-sig"),
                file_name="selection_metrics_selected_months.csv",
                mime="text/csv",
            )

    with selection_tab2:
        left, right = st.columns(2)

        with left:
            st.markdown("#### 满勤候选")
            if full_attendance.empty:
                st.info("当前没有总达标率 100% 的成员。")
            else:
                view = full_attendance[
                    [
                        "姓名",
                        "达标月份数",
                        "统计月份数",
                        "总达标率",
                    ]
                ].copy()
                view["总达标率"] = view["总达标率"].map(lambda x: f"{float(x):.1f}%")
                st.dataframe(view, use_container_width=True, hide_index=True)

        with right:
            st.markdown("#### 进步展示资格")
            st.caption("达标率 50% 以上的成员可进入进步展示候选范围。")
            if progress_eligible.empty:
                st.info("当前还没有成员达到 50% 资格线。")
            else:
                view = progress_eligible[
                    [
                        "姓名",
                        "达标月份数",
                        "统计月份数",
                        "总达标率",
                    ]
                ].copy()
                view["总达标率"] = view["总达标率"].map(lambda x: f"{float(x):.1f}%")
                st.dataframe(view, use_container_width=True, hide_index=True)

    with selection_tab3:
        st.caption("每个人在所选月份里的逐月达标情况。")
        st.dataframe(monthly_detail, use_container_width=True, hide_index=True)

        st.download_button(
            label="导出月度明细 CSV",
            data=monthly_detail.to_csv(index=False).encode("utf-8-sig"),
            file_name="selection_monthly_detail_selected_months.csv",
            mime="text/csv",
        )

    st.divider()

    with st.expander("记录统计参考"):
        record_keeper = st.secrets.get("SELECTION_RECORD_KEEPER", "未设置")
        below_50_count = len(below_50)

        st.caption(
            "这里仅用于内部记录统计参考，不参与上面的主要排名。"
        )

        info_col1, info_col2 = st.columns(2)

        with info_col1:
            st.metric("记录统计负责人", record_keeper)

        with info_col2:
            st.metric("低于 50% 人数", f"{below_50_count} 人")

        if below_50.empty:
            st.write("所选月份内没有低于 50% 达标率的成员。")
        else:
            view = below_50[
                [
                    "姓名",
                    "达标月份数",
                    "统计月份数",
                    "总达标率",
                ]
            ].copy()
            view["总达标率"] = view["总达标率"].map(lambda x: f"{float(x):.1f}%")
            st.dataframe(view, use_container_width=True, hide_index=True)


# -----------------------------
# Gallery helpers
# -----------------------------


def render_recent_image_gallery(df_all: pd.DataFrame, limit: int = 12):
    st.markdown("### 运动相册")

    if df_all.empty or "file_path" not in df_all.columns:
        st.info("还没有可展示的图片。")
        return

    gallery = df_all.copy()
    gallery["file_path"] = gallery["file_path"].fillna("").astype(str)
    gallery = gallery[gallery["file_path"].str.strip() != ""]

    if gallery.empty:
        st.info("还没有可展示的图片。")
        return

    sort_col = "submitted_at" if "submitted_at" in gallery.columns else "activity_date"
    gallery = gallery.sort_values(sort_col, ascending=False).head(limit).reset_index(drop=True)

    if "gallery_index" not in st.session_state:
        st.session_state.gallery_index = 0

    if st.session_state.gallery_index >= len(gallery):
        st.session_state.gallery_index = 0

    st.caption("最近上传的运动记录。使用左右按钮切换，也可以在下方缩略图中选择。")

    control_left, control_mid, control_right = st.columns([1, 3, 1])

    with control_left:
        if st.button("← 上一张", use_container_width=True, key="gallery_prev"):
            st.session_state.gallery_index = (st.session_state.gallery_index - 1) % len(gallery)
            st.rerun()

    with control_mid:
        st.markdown(
            f"<div style='text-align:center; color:#6b7280; padding-top:0.5rem;'>"
            f"{st.session_state.gallery_index + 1} / {len(gallery)}"
            f"</div>",
            unsafe_allow_html=True,
        )

    with control_right:
        if st.button("下一张 →", use_container_width=True, key="gallery_next"):
            st.session_state.gallery_index = (st.session_state.gallery_index + 1) % len(gallery)
            st.rerun()

    row = gallery.iloc[st.session_state.gallery_index]
    file_path = str(row.get("file_path", "")).strip()

    try:
        signed_url = create_signed_image_url(file_path)
    except Exception:
        signed_url = None

    caption = (
        f"{row.get('name', '')} ｜ "
        f"{row.get('activity_date', '')} ｜ "
        f"{row.get('activity_type', '')} ｜ "
        f"{row.get('duration_min', '')} 分钟"
    )

    st.markdown(
        """
        <style>
        .gallery-frame {
            border-radius: 22px;
            border: 1px solid rgba(120, 92, 65, 0.14);
            padding: 0.8rem;
            background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(250,248,245,0.92));
            box-shadow: 0 12px 28px rgba(55, 48, 40, 0.07);
            margin-top: 0.5rem;
            margin-bottom: 1rem;
        }
        </style>
        <div class="gallery-frame">
        """,
        unsafe_allow_html=True,
    )

    if signed_url:
        st.image(signed_url, caption=caption, use_container_width=True)
    else:
        st.warning("这张图片的临时链接生成失败。")

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("#### 缩略图")

    thumb_cols = st.columns(4)

    for i, (_, item) in enumerate(gallery.iterrows()):
        with thumb_cols[i % 4]:
            thumb_url = None
            try:
                thumb_url = create_signed_image_url(str(item.get("file_path", "")).strip())
            except Exception:
                thumb_url = None

            if thumb_url:
                st.image(thumb_url, use_container_width=True)

            label = f"{i + 1}. {item.get('name', '')}"
            if st.button(label, key=f"gallery_thumb_{i}", use_container_width=True):
                st.session_state.gallery_index = i
                st.rerun()

    with st.expander("查看图片对应记录"):
        display_cols = [
            col
            for col in [
                "name",
                "activity_date",
                "activity_type",
                "duration_min",
                "note",
                "submitted_at",
            ]
            if col in gallery.columns
        ]

        records = gallery[display_cols].rename(
            columns={
                "name": "姓名",
                "activity_date": "运动日期",
                "activity_type": "运动类型",
                "duration_min": "运动分钟",
                "note": "备注",
                "submitted_at": "提交时间",
            }
        )

        st.dataframe(records, use_container_width=True, hide_index=True)


# -----------------------------
# Dashboard tab
# -----------------------------

with tab_dashboard:
    st.subheader("运动总览")

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取打卡数据失败。")
        st.exception(e)
        st.stop()

    today = get_now_local().date()
    week_start, week_end = get_week_range(today)
    month_start = today.replace(day=1)
    month_end = today

    if df_all.empty:
        st.info("还没有记录。")
    else:
        df_week = filter_by_date_range(df_all, week_start, week_end)
        df_month = filter_by_date_range(df_all, month_start, month_end)
        df_today = filter_by_date_range(df_all, today, today)

        st.caption(
            f"今日 {today} ｜ 本周 {format_date_range(week_start, week_end)} ｜ "
            f"本月至今 {format_date_range(month_start, month_end)}"
        )

        # -----------------------------
        # Overview metrics
        # -----------------------------
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "今日参与人数",
                df_today["name"].nunique() if not df_today.empty else 0,
            )

        with col2:
            st.metric(
                "本周总分钟",
                int(df_week["duration_min"].sum()) if not df_week.empty else 0,
            )

        with col3:
            st.metric(
                "本月总分钟",
                int(df_month["duration_min"].sum()) if not df_month.empty else 0,
            )

        with col4:
            st.metric(
                "本月参与人数",
                df_month["name"].nunique() if not df_month.empty else 0,
            )

        st.divider()

        # BEGIN monthly goal status dashboard
        # -----------------------------
        # Monthly goal status
        # -----------------------------
        st.markdown("### 本月达标")

        target_checkins, target_minutes = get_monthly_goal_settings()

        st.caption(
            f"规则：本月完成 {target_checkins} 次有效运动；"
            f"每次不少于 {target_minutes} 分钟。"
        )

        monthly_goal_table = make_current_month_goal_table(df_month)

        goal_col1, goal_col2, goal_col3 = st.columns(3)

        achieved_count = (
            int((monthly_goal_table["本月状态"] == "✅ 已达标").sum())
            if not monthly_goal_table.empty
            else 0
        )

        active_member_count = len(get_active_members())

        with goal_col1:
            st.metric("已达标", f"{achieved_count} / {active_member_count}")

        with goal_col2:
            st.metric(
                "未达标",
                max(active_member_count - achieved_count, 0),
            )

        with goal_col3:
            achievement_rate = (
                achieved_count / active_member_count * 100
                if active_member_count > 0
                else 0
            )
            st.metric("达标率", f"{achievement_rate:.1f}%")

        monthly_goal_view = monthly_goal_table.rename(
            columns={
                "有效运动次数": "有效次数",
                "总打卡次数": "打卡",
                "总运动分钟": "分钟",
                "达标进度": "进度",
                "还差有效运动次数": "还差",
                "本月状态": "状态",
                "达标提示": "提示",
            }
        )

        st.dataframe(
            monthly_goal_view,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        st.markdown("### 长期记录")

        goal_history = make_monthly_goal_history(df_all, today)
        goal_streak_table = make_goal_streak_table(goal_history, today)

        st.caption(
            "连续月份只统计已结束月份；本月进度单独显示。"
        )

        goal_streak_view = goal_streak_table.rename(
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

        st.dataframe(
            goal_streak_view,
            use_container_width=True,
            hide_index=True,
        )

        with st.expander("每月明细"):
            history_view = goal_history.copy()
            history_view["是否达标"] = history_view["是否达标"].map(
                {True: "✅ 已达标", False: "未达标"}
            )
            history_view["达标提示"] = history_view["还差有效运动次数"].apply(
                lambda x: "已达标" if int(x) == 0 else f"还差 {int(x)} 次"
            )
            history_view = history_view.rename(
                columns={
                    "有效运动次数": "有效次数",
                    "总打卡次数": "打卡",
                    "总运动分钟": "分钟",
                    "是否达标": "状态",
                    "还差有效运动次数": "还差",
                    "达标提示": "提示",
                }
            )

            st.dataframe(
                history_view.sort_values(["月份", "姓名"], ascending=[False, True]),
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        # END monthly goal status dashboard

        # -----------------------------
        # Leaderboards
        # -----------------------------
        left, right = st.columns(2)

        with left:
            st.markdown("### 本周运动时长")
            weekly_board = make_leaderboard(df_week)

            if weekly_board.empty:
                st.info("本周还没有打卡记录。")
            else:
                st.dataframe(
                    weekly_board,
                    use_container_width=True,
                    hide_index=True,
                )
                st.bar_chart(weekly_board.set_index("姓名")["总运动分钟"])

        with right:
            st.markdown("### 本月运动时长")
            monthly_board = make_leaderboard(df_month)

            if monthly_board.empty:
                st.info("本月还没有打卡记录。")
            else:
                st.dataframe(
                    monthly_board,
                    use_container_width=True,
                    hide_index=True,
                )
                st.bar_chart(monthly_board.set_index("姓名")["总运动分钟"])

        st.divider()

        # -----------------------------
        # Cumulative daily minutes
        # -----------------------------
        st.markdown("### 本月累计运动时长")

        cumulative_month = make_cumulative_minutes(df_month, month_start, month_end)

        if cumulative_month.empty:
            st.info("本月还没有可展示的累计数据。")
        else:
            st.line_chart(cumulative_month)

        st.divider()

        # -----------------------------
        # Activity type leaderboard
        # -----------------------------
        st.markdown("### 运动类型分布")

        activity_board = make_activity_leaderboard(df_month)

        if activity_board.empty:
            st.info("本月还没有运动类型数据。")
        else:
            st.dataframe(
                activity_board,
                use_container_width=True,
                hide_index=True,
            )
            st.bar_chart(activity_board.set_index("运动类型")["总运动分钟"])

        st.divider()

        # -----------------------------
        # Diversity leaderboard
        # -----------------------------
        st.markdown("### 运动多样性")

        diversity_board = make_diversity_leaderboard(df_month)

        if diversity_board.empty:
            st.info("本月还没有运动多样性数据。")
        else:
            st.dataframe(
                diversity_board,
                use_container_width=True,
                hide_index=True,
            )

        st.divider()

        # -----------------------------
        # Daily presence table
        # -----------------------------
        st.markdown("### 本周记录")

        presence_week = make_daily_presence_table(df_week, week_start, week_end)

        st.dataframe(
            presence_week,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        # -----------------------------
        # Recent records
        # -----------------------------
        with st.expander("最近记录"):
            recent = (
                df_all.sort_values("submitted_at", ascending=False)
                .head(30)
                .loc[
                    :,
                    [
                        "name",
                        "activity_date",
                        "activity_type",
                        "duration_min",
                        "note",
                        "submitted_at",
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
                    }
                )
            )

            st.dataframe(
                recent,
                use_container_width=True,
                hide_index=True,
            )


# -----------------------------
# Lab goal tab
# -----------------------------

with tab_goal:
    st.subheader("本月目标")

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取记录失败。")
        st.exception(e)
        st.stop()

    today = get_now_local().date()
    month_start, month_end = get_month_range(today)

    df_month = filter_by_date_range(df_all, month_start, month_end)
    stats = make_energy_pool_stats(df_month)

    target_checkins_per_person = int(
        st.secrets.get("MONTHLY_TARGET_CHECKINS_PER_PERSON", 8)
    )
    target_minutes_per_checkin = int(
        st.secrets.get("MONTHLY_TARGET_MINUTES_PER_CHECKIN", 30)
    )
    energy_credit_cap_min = int(
        st.secrets.get("ENERGY_CREDIT_CAP_MIN", target_minutes_per_checkin)
    )

    progress_percent = stats["progress"] * 100

    st.caption(
        f"{month_start} 至 {month_end} ｜ "
        f"截至 {today} ｜ "
        f"{stats['member_count']} 人"
    )

    st.markdown(
        f"""
        每人 **{target_checkins_per_person} 次**，每次 **{target_minutes_per_checkin} 分钟**。  
        每条记录最多计入 **{energy_credit_cap_min} 分钟**；多出来的时间仍会完整保留在总览里。
        """
    )

    st.markdown(f"### 能量池 {progress_percent:.1f}%")
    render_energy_bowl(stats["progress"])

    row1_col1, row1_col2 = st.columns(2)
    row2_col1, row2_col2 = st.columns(2)

    with row1_col1:
        st.metric(
            "已积累",
            f"{stats['actual_energy_minutes']} / {stats['target_energy_minutes']} 分钟",
        )

    with row1_col2:
        st.metric(
            "还差",
            f"{stats['remaining_minutes']} 分钟",
        )

    with row2_col1:
        st.metric(
            "约需",
            f"{stats['remaining_checkins_equivalent']:.1f} 次",
        )

    with row2_col2:
        st.metric(
            "参与",
            f"{stats['participant_count']} / {stats['member_count']}",
        )

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

    contribution_table = make_energy_pool_contribution_table(stats["df_goal"])
    contribution_view = contribution_table.rename(
        columns={
            "能量贡献": "贡献",
            "实际运动分钟": "实际分钟",
        }
    )

    st.dataframe(
        contribution_view,
        use_container_width=True,
        hide_index=True,
    )

    if not contribution_table.empty:
        st.bar_chart(contribution_table.set_index("姓名")["能量贡献"])

    st.caption("能量池看共同进度；总览保留每个人的完整记录。")




# -----------------------------
# Selection tab
# -----------------------------

with tab_selection:
    st.subheader("运动评选")

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取记录失败。")
        st.exception(e)
        st.stop()

    today = get_now_local().date()
    render_selection_board(df_all, today)


# -----------------------------
# Gallery tab
# -----------------------------

with tab_gallery:
    st.subheader("运动相册")

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取记录失败。")
        st.exception(e)
        st.stop()

    render_recent_image_gallery(df_all, limit=12)


# -----------------------------
# Admin tab
# -----------------------------

with tab_admin:
    st.subheader("后台")

    admin_password = st.text_input("管理员密码", type="password")

    if not check_password(admin_password, st.secrets["ADMIN_PASSWORD"]):
        st.info("输入密码后查看完整记录。")
        st.stop()

    def _clean_text(value) -> str:
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except TypeError:
            pass
        return str(value)

    def _safe_int(value, default: int = 0) -> int:
        try:
            if pd.isna(value):
                return default
            return int(value)
        except Exception:
            return default

    def _prepare_export_csv(dataframe: pd.DataFrame) -> bytes:
        return dataframe.to_csv(index=False).encode("utf-8-sig")

    def _display_records(dataframe: pd.DataFrame) -> pd.DataFrame:
        return dataframe.rename(
            columns={
                "id": "ID",
                "name": "姓名",
                "activity_date": "日期",
                "activity_type": "运动类型",
                "duration_min": "分钟",
                "note": "备注",
                "submitted_at": "提交时间",
                "file_name": "图片文件名",
                "file_path": "图片路径",
            }
        )

    def _delete_records(records: pd.DataFrame):
        ids = records["id"].dropna().astype(int).tolist()
        file_paths = [
            _clean_text(x)
            for x in records.get("file_path", pd.Series(dtype=str)).tolist()
            if _clean_text(x)
        ]

        if file_paths:
            supabase.storage.from_(BUCKET_NAME).remove(file_paths)

        if ids:
            supabase.table("exercise_checkins").delete().in_("id", ids).execute()

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

        df["activity_date"] = pd.to_datetime(df["activity_date"], errors="coerce").dt.date
        df["submitted_at"] = pd.to_datetime(df["submitted_at"], errors="coerce")
        df["duration_min"] = (
            pd.to_numeric(df["duration_min"], errors="coerce")
            .fillna(0)
            .astype(int)
        )

        st.markdown("### 筛选")

        filter_col1, filter_col2, filter_col3 = st.columns(3)

        with filter_col1:
            all_names = sorted(df["name"].dropna().astype(str).unique().tolist())
            selected_names = st.multiselect(
                "姓名",
                all_names,
                default=[],
                placeholder="全部",
            )

        with filter_col2:
            all_activity_types = sorted(
                df["activity_type"].dropna().astype(str).unique().tolist()
            )
            selected_types = st.multiselect(
                "运动类型",
                all_activity_types,
                default=[],
                placeholder="全部",
            )

        with filter_col3:
            valid_dates = df["activity_date"].dropna()
            if valid_dates.empty:
                default_date_range = (get_now_local().date(), get_now_local().date())
            else:
                default_date_range = (valid_dates.min(), valid_dates.max())

            selected_date_range = st.date_input(
                "日期范围",
                value=default_date_range,
            )

        filtered_df = df.copy()

        if selected_names:
            filtered_df = filtered_df[filtered_df["name"].isin(selected_names)]

        if selected_types:
            filtered_df = filtered_df[filtered_df["activity_type"].isin(selected_types)]

        if isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
            start_date, end_date = selected_date_range
            filtered_df = filtered_df[
                (filtered_df["activity_date"] >= start_date)
                & (filtered_df["activity_date"] <= end_date)
            ]

        filtered_df = filtered_df.sort_values("submitted_at", ascending=False)

        st.caption(f"当前筛选：{len(filtered_df)} 条记录")

        st.divider()

        st.markdown("### 批量导出")

        export_col1, export_col2 = st.columns(2)

        with export_col1:
            st.download_button(
                label="导出当前筛选 CSV",
                data=_prepare_export_csv(filtered_df),
                file_name="exercise_checkins_filtered.csv",
                mime="text/csv",
                disabled=filtered_df.empty,
            )

        st.divider()

        st.markdown("### 批量选择")

        batch_view = filtered_df.copy()
        batch_view.insert(0, "选择", False)

        batch_view = batch_view[
            [
                "选择",
                "id",
                "name",
                "activity_date",
                "activity_type",
                "duration_min",
                "note",
                "submitted_at",
                "file_name",
                "file_path",
            ]
        ].rename(
            columns={
                "id": "ID",
                "name": "姓名",
                "activity_date": "日期",
                "activity_type": "运动类型",
                "duration_min": "分钟",
                "note": "备注",
                "submitted_at": "提交时间",
                "file_name": "图片文件名",
                "file_path": "图片路径",
            }
        )

        edited_batch_view = st.data_editor(
            batch_view,
            use_container_width=True,
            hide_index=True,
            disabled=[
                "ID",
                "姓名",
                "日期",
                "运动类型",
                "分钟",
                "备注",
                "提交时间",
                "图片文件名",
                "图片路径",
            ],
            column_config={
                "选择": st.column_config.CheckboxColumn(
                    "选择",
                    help="勾选后可批量导出或删除。",
                    default=False,
                )
            },
            key="batch_record_selector",
        )

        selected_ids = (
            edited_batch_view.loc[edited_batch_view["选择"], "ID"]
            .dropna()
            .astype(int)
            .tolist()
        )

        selected_df = filtered_df[filtered_df["id"].isin(selected_ids)].copy()

        st.caption(f"已选择：{len(selected_df)} 条")

        batch_col1, batch_col2 = st.columns(2)

        with batch_col1:
            st.download_button(
                label="导出勾选记录 CSV",
                data=_prepare_export_csv(selected_df),
                file_name="exercise_checkins_selected.csv",
                mime="text/csv",
                disabled=selected_df.empty,
            )

        with batch_col2:
            confirm_batch_delete = st.checkbox(
                f"确认删除已勾选的 {len(selected_df)} 条记录",
                disabled=selected_df.empty,
                key="confirm_batch_delete",
            )

            batch_delete_clicked = st.button(
                "批量删除勾选记录",
                type="secondary",
                disabled=selected_df.empty or not confirm_batch_delete,
                key="batch_delete_records",
            )

        if batch_delete_clicked:
            try:
                _delete_records(selected_df)
                load_checkins.clear()
                st.success(f"已删除 {len(selected_df)} 条记录。")
                st.rerun()
            except Exception as e:
                st.error("批量删除失败。")
                st.exception(e)

        st.divider()

        st.markdown("### 单条修改")

        edit_source_df = filtered_df if not filtered_df.empty else df

        options = [
            (
                f"{row['id']} | {row['name']} | {row['activity_date']} | "
                f"{row['activity_type']} | {row['duration_min']} 分钟"
            )
            for _, row in edit_source_df.iterrows()
        ]

        if not options:
            st.info("当前筛选下没有可修改的记录。")
            st.stop()

        selected = st.selectbox("选择记录", options)
        selected_id = int(selected.split("|")[0].strip())

        selected_row = df[df["id"] == selected_id].iloc[0]

        left, right = st.columns([1, 1])

        with left:
            st.markdown("#### 当前图片")

            current_file_path = _clean_text(selected_row.get("file_path"))
            current_file_name = _clean_text(selected_row.get("file_name"))

            if current_file_path:
                signed_url = create_signed_image_url(current_file_path)

                if signed_url:
                    st.image(
                        signed_url,
                        caption=current_file_name or current_file_path,
                        use_container_width=True,
                    )
                else:
                    st.warning("图片临时链接生成失败。")
            else:
                st.info("这条记录没有图片路径。")

        with right:
            st.markdown("#### 记录信息")

            members = list(st.secrets.get("MEMBERS", []))
            current_name = _clean_text(selected_row.get("name"))

            name_options = members.copy()
            if current_name and current_name not in name_options:
                name_options = [current_name] + name_options

            if not name_options:
                name_options = [current_name] if current_name else [""]

            current_activity = _clean_text(selected_row.get("activity_type"))
            activity_options = list(ACTIVITY_TYPES)

            if current_activity and current_activity not in activity_options:
                activity_options = [current_activity] + activity_options

            current_date = pd.to_datetime(
                selected_row.get("activity_date"),
                errors="coerce",
            )

            if pd.isna(current_date):
                current_date = get_now_local().date()
            else:
                current_date = current_date.date()

            current_duration = _safe_int(selected_row.get("duration_min"), 30)
            current_note = _clean_text(selected_row.get("note"))

            with st.form(f"edit_record_form_{selected_id}"):
                edited_name = st.selectbox(
                    "姓名",
                    name_options,
                    index=name_options.index(current_name) if current_name in name_options else 0,
                )

                edited_date = st.date_input(
                    "运动日期",
                    value=current_date,
                )

                edited_activity = st.selectbox(
                    "运动类型",
                    activity_options,
                    index=activity_options.index(current_activity)
                    if current_activity in activity_options
                    else 0,
                )

                edited_duration = st.number_input(
                    "运动时长（分钟）",
                    min_value=MIN_SUBMIT_MINUTES,
                    max_value=600,
                    value=max(current_duration, MIN_SUBMIT_MINUTES),
                    step=5,
                    help=f"每条记录至少 {MIN_SUBMIT_MINUTES} 分钟。",
                )

                edited_note = st.text_area(
                    "今天有什么想说的？",
                    value=current_note,
                )

                replacement_file = st.file_uploader(
                    f"替换截图或照片（可选，原图不超过 {MAX_SOURCE_UPLOAD_MB} MB，系统会自动压缩）",
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=False,
                    key=f"replacement_file_{selected_id}",
                )

                save_clicked = st.form_submit_button("保存修改")

            if save_clicked:
                try:
                    update_row = {
                        "name": edited_name.strip(),
                        "activity_date": edited_date.isoformat(),
                        "activity_type": edited_activity,
                        "duration_min": int(edited_duration),
                        "note": edited_note.strip() or None,
                    }

                    old_file_path = current_file_path

                    if replacement_file is not None:
                        new_file_info = upload_image(
                            replacement_file,
                            edited_name.strip(),
                            edited_date,
                        )

                        update_row.update(
                            {
                                "file_path": new_file_info["file_path"],
                                "file_name": new_file_info["file_name"],
                                "file_mime": new_file_info["file_mime"],
                                "file_size": new_file_info["file_size"],
                            }
                        )

                    supabase.table("exercise_checkins").update(update_row).eq(
                        "id",
                        selected_id,
                    ).execute()

                    if replacement_file is not None and old_file_path:
                        try:
                            supabase.storage.from_(BUCKET_NAME).remove([old_file_path])
                        except Exception:
                            st.warning("记录已修改，但旧图片删除失败。可稍后手动清理。")

                    load_checkins.clear()
                    st.success("已保存。")
                    st.rerun()

                except Exception as e:
                    st.error("保存失败。")
                    st.exception(e)

        st.divider()
        st.markdown("### 单条删除")

        st.warning("删除会同时删除数据库记录和对应图片。这个操作不能撤回。")

        confirm_delete = st.checkbox(
            f"确认删除 ID {selected_id} 这条记录",
            key=f"confirm_delete_{selected_id}",
        )

        delete_clicked = st.button(
            "删除这条记录",
            type="secondary",
            disabled=not confirm_delete,
            key=f"delete_record_{selected_id}",
        )

        if delete_clicked:
            try:
                selected_record_df = df[df["id"] == selected_id].copy()
                _delete_records(selected_record_df)

                load_checkins.clear()
                st.success("已删除。")
                st.rerun()

            except Exception as e:
                st.error("删除失败。")
                st.exception(e)

    except Exception as e:
        st.error("后台读取失败。")
        st.exception(e)
