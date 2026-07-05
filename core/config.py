"""集中管理配置项。所有 st.secrets 读取都在这里，方便查找和调整。"""
from datetime import datetime

import streamlit as st

# -----------------------------
# 存储 / 图片
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

# -----------------------------
# 时间 / 规则
# -----------------------------
APP_TIMEZONE = st.secrets.get("APP_TIMEZONE", "Asia/Shanghai")

MIN_SUBMIT_MINUTES = int(
    st.secrets.get(
        "MIN_SUBMIT_MINUTES",
        st.secrets.get("MONTHLY_TARGET_MINUTES_PER_CHECKIN", 30),
    )
)

# 该日期之前的记录属于历史补卡，不强制上传照片
PHOTO_REQUIRED_START_DATE = datetime(2026, 5, 1).date()

# 补卡判定：提交时间比运动日期晚 N 天以上，视为补卡
BACKFILL_GRACE_DAYS = int(st.secrets.get("BACKFILL_GRACE_DAYS", 2))

MONTHLY_TARGET_CHECKINS_PER_PERSON = int(
    st.secrets.get("MONTHLY_TARGET_CHECKINS_PER_PERSON", 8)
)
MONTHLY_TARGET_MINUTES_PER_CHECKIN = int(
    st.secrets.get("MONTHLY_TARGET_MINUTES_PER_CHECKIN", 30)
)
ENERGY_CREDIT_CAP_MIN = int(
    st.secrets.get("ENERGY_CREDIT_CAP_MIN", MONTHLY_TARGET_MINUTES_PER_CHECKIN)
)
FEMALE_MONTHLY_TARGET_CHECKINS = int(
    st.secrets.get("FEMALE_MONTHLY_TARGET_CHECKINS", 7)
)

HALF_CREDIT_GOAL_CREDIT = float(st.secrets.get("HALF_CREDIT_GOAL_CREDIT", 0.5))
HALF_CREDIT_RECORD_CAP = int(st.secrets.get("HALF_CREDIT_RECORD_CAP", 8))

ACTIVITY_TYPE_SEPARATOR = "、"
PRIMARY_ACTIVITY_SUFFIX = "（主要）"
DEFAULT_HALF_CREDIT_ACTIVITY_TYPES = ["散步", "走够一万步", "康复训练", "台球"]

# 注意：字符串形式的配置在 rules.py 里解析（需要 split_activity_types），
# 修复了旧版本在此处直接调用未定义函数导致的 NameError。
RAW_HALF_CREDIT_ACTIVITY_TYPES = st.secrets.get(
    "HALF_CREDIT_ACTIVITY_TYPES",
    DEFAULT_HALF_CREDIT_ACTIVITY_TYPES,
)

# -----------------------------
# 成员
# -----------------------------
MEMBER_GENDER_MAP = {
    "王平": "女",
    "李城炫": "男",
    "刘新新": "女",
    "赵阳": "男",
    "戴雨池": "男",
    "马春梅": "女",
    "陈雨晴": "女",
    "蔡远荣": "男",
    "陈飞帆": "女",
    "张函齐": "男",
    "郑盈颖": "女",
    "杨文威": "男",
}


def get_members() -> list[str]:
    return list(st.secrets.get("MEMBERS", []))


def get_active_members() -> list[str]:
    """参与本月目标统计的成员。优先 ACTIVE_MEMBERS，否则退回 MEMBERS。"""
    active = list(st.secrets.get("ACTIVE_MEMBERS", []))
    return active if active else get_members()


# -----------------------------
# 选项
# -----------------------------
ACTIVITY_TYPES = [
    "健身", "力量训练", "跑步", "爬坡", "游泳", "浮潜", "桨板", "骑行",
    "康复训练", "散步", "走够一万步", "羽毛球", "乒乓球", "徒步", "登山",
    "跳绳", "呼啦圈", "爬楼", "椭圆机", "踏步机", "划船机", "瑜伽",
    "普拉提", "篮球", "足球", "排球", "网球", "匹克球", "台球", "舞蹈",
    "健身操", "其他",
]

MESSAGE_REACTIONS = [
    ("pat", "👍", "点赞"),
    ("flower", "🌸", "给你送花"),
    ("smile", "😄", "笑死了"),
    ("cry", "🥲", "感性了"),
]

MOOD_OPTIONS = [
    ("happy", "😊", "开心"),
    ("accomplished", "🌟", "成就感"),
    ("relaxed", "😌", "放松"),
    ("tired_good", "😮‍💨", "累"),
    ("annoyed", "😤", "有点烦"),
]

MOOD_LOOKUP = {
    key: {"emoji": emoji, "label": label} for key, emoji, label in MOOD_OPTIONS
}
MOOD_KEYS = [key for key, _, _ in MOOD_OPTIONS]
MOOD_SEPARATOR = "、"
CUSTOM_MOOD_PREFIX = "custom:"
