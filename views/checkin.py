"""打卡页：手机优先。主流程一屏完成，心情/碎碎念折叠为可选项。"""
import hashlib

import streamlit as st

from core.config import (
    MAX_SOURCE_UPLOAD_MB,
    MIN_SUBMIT_MINUTES,
    MOOD_KEYS,
    PHOTO_REQUIRED_START_DATE,
    ACTIVITY_TYPES,
    get_members,
)
from core.db import get_now_local, insert_checkin
from core.images import upload_image
from core.rules import (
    format_mood_key,
    join_activity_types,
    join_mood_values,
    split_activity_types,
)


def _make_submit_fingerprint(
    name, activity_date, activity_types, duration_min, mood_key, note, uploaded_file
) -> str:
    photo_identity = "no-photo"
    if uploaded_file is not None:
        photo_identity = (
            f"{getattr(uploaded_file, 'name', '')}:{getattr(uploaded_file, 'size', '')}"
        )
    raw = "\t".join(
        [
            str(name).strip(),
            str(activity_date),
            join_activity_types(activity_types),
            str(int(duration_min)),
            str(mood_key or ""),
            str(note or "").strip(),
            photo_identity,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def checkin_page():
    st.subheader("今天运动了么？")

    submit_success_message = st.session_state.pop("submit_success_message", None)

    if "submit_form_version" not in st.session_state:
        st.session_state["submit_form_version"] = 0

    if st.session_state.pop("reset_submit_activity_types", False):
        for key in list(st.session_state.keys()):
            if str(key).startswith("submit_activity_types"):
                st.session_state.pop(key, None)

    if submit_success_message:
        st.session_state["submit_recently_completed"] = True
        st.success(
            f"✅ {submit_success_message} 为了避免重复提交，同一条内容会被临时锁定。"
        )
        if hasattr(st, "toast"):
            st.toast("✅ 已提交，这条记录已经写入。", icon="✅")

    with st.popover("查看打卡规则") if hasattr(st, "popover") else st.expander("打卡规则"):
        st.markdown(
            f"""
            - 可以选择多个运动类型。
            - 一次打卡的总运动时长需要 **不少于 {MIN_SUBMIT_MINUTES} 分钟** 才能提交。
            - 一天可以提交多次，但同一个人同一天最多只计入 1 次有效运动。
            - 散步、走够一万步、康复训练、台球默认按半次有效打卡计入目标，最多计入 8 条，即 4 次有效运动。
            - {PHOTO_REQUIRED_START_DATE.year}年{PHOTO_REQUIRED_START_DATE.month}月之前的历史补卡不需要上传照片，之后必须上传截图或照片。
            - 上传图片会自动压缩，不需要自己处理。
            """
        )

    members = get_members()
    if members:
        name = st.selectbox("姓名", members, key="submit_name")
    else:
        name = st.text_input("姓名", key="submit_name")

    activity_date = st.date_input(
        "运动日期", value=get_now_local().date(), key="submit_activity_date"
    )

    photo_required = activity_date >= PHOTO_REQUIRED_START_DATE
    if photo_required:
        st.caption("这一天的打卡需要上传截图或照片。")
    else:
        st.caption("历史补卡：这一天的记录不需要上传照片。")

    activity_types_key = (
        f"submit_activity_types_{st.session_state['submit_form_version']}"
    )
    if hasattr(st, "pills"):
        activity_types = st.pills(
            "运动类型（可多选）",
            ACTIVITY_TYPES,
            selection_mode="multi",
            default=[],
            help="一次运动包含多种内容时可以多选，例如：爬坡、力量训练。",
            key=activity_types_key,
        )
    else:
        activity_types = st.multiselect(
            "运动类型（可多选）",
            ACTIVITY_TYPES,
            default=[],
            key=activity_types_key,
        )
    activity_types = activity_types or []

    if not activity_types:
        st.info("请选择至少一种运动类型。")

    selected_types = split_activity_types(activity_types)
    steps_only = selected_types == ["走够一万步"]
    duration_key = (
        f"submit_duration_min_{st.session_state['submit_form_version']}_"
        f"{'steps_only' if steps_only else 'normal'}"
    )

    if steps_only:
        st.info("只选择“走够一万步”时，系统固定计为 30 分钟。")
        duration_min = st.number_input(
            "总运动时长（分钟）",
            min_value=30, max_value=30, value=30, step=1,
            key=duration_key, disabled=True,
        )
    else:
        duration_min = st.number_input(
            "总运动时长（分钟）",
            min_value=MIN_SUBMIT_MINUTES, max_value=600,
            value=MIN_SUBMIT_MINUTES, step=5,
            help=f"这次打卡的总时长，不少于 {MIN_SUBMIT_MINUTES} 分钟。",
            key=duration_key,
        )

    uploaded_file = st.file_uploader(
        f"上传截图或照片（原图不超过 {MAX_SOURCE_UPLOAD_MB} MB，系统会自动压缩）",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=False,
        key="submit_uploaded_file",
    )

    # 心情和碎碎念是可选项，折叠起来缩短手机端表单长度
    with st.expander("记录心情和碎碎念（可选）", expanded=False):
        if hasattr(st, "pills"):
            selected_mood_keys = st.pills(
                "运动后的心情（可多选）",
                MOOD_KEYS,
                selection_mode="multi",
                default=[],
                format_func=format_mood_key,
                key="submit_mood_keys",
            )
        else:
            selected_mood_keys = st.multiselect(
                "运动后的心情（可多选）",
                MOOD_KEYS,
                default=[],
                format_func=format_mood_key,
                key="submit_mood_keys",
            )

        mood_col1, mood_col2 = st.columns([1, 3])
        with mood_col1:
            custom_mood_emoji = st.text_input(
                "自定义 emoji", placeholder="🔥", max_chars=12,
                key="submit_custom_mood_emoji",
            )
        with mood_col2:
            custom_mood_label = st.text_input(
                "自定义状态", placeholder="充满power / 腰酸背痛 / 我很强壮",
                key="submit_custom_mood_label",
            )

        note = st.text_area(
            "今天有什么想说的？",
            placeholder="记录一点今天的状态、心情、运动感受，或者随便写一句话。",
            key="submit_note",
        )

    custom_mood_incomplete = bool(custom_mood_emoji.strip()) ^ bool(
        custom_mood_label.strip()
    )
    mood_key = join_mood_values(selected_mood_keys, custom_mood_emoji, custom_mood_label)

    fingerprint = _make_submit_fingerprint(
        name, activity_date, activity_types, duration_min, mood_key, note, uploaded_file
    )
    submit_locked = (
        st.session_state.get("submit_recently_completed", False)
        and st.session_state.get("last_submit_fingerprint") == fingerprint
    )
    if submit_locked:
        st.warning(
            "✅ 刚才这条记录已经提交成功。为了防止重复提交，请修改任意内容后再提交新记录。"
        )

    submitted = st.button(
        "提交打卡",
        disabled=not activity_types
        or submit_locked
        or st.session_state.get("submit_in_progress", False),
        type="primary",
        key="submit_checkin_button",
        use_container_width=True,
    )

    if not submitted:
        return

    if (
        st.session_state.get("submit_recently_completed", False)
        and st.session_state.get("last_submit_fingerprint") == fingerprint
    ):
        st.warning("这条记录刚才已经提交过了，已阻止重复提交。")
        return

    st.session_state["submit_in_progress"] = True
    name = name.strip()

    error = None
    if not name:
        error = "姓名不能为空。"
    elif not activity_types:
        error = "请选择至少一种运动类型。"
    elif custom_mood_incomplete:
        error = "自定义心情需要同时填写 emoji 和状态文字。"
    elif photo_required and uploaded_file is None:
        error = "这一天的打卡需要上传截图或照片。"
    elif int(duration_min) < MIN_SUBMIT_MINUTES:
        error = f"每次打卡总时长不少于 {MIN_SUBMIT_MINUTES} 分钟。"

    if error:
        st.session_state["submit_in_progress"] = False
        st.error(error)
        return

    try:
        file_info = None
        if uploaded_file is not None:
            with st.spinner("正在压缩并上传图片…"):
                file_info = upload_image(uploaded_file, name, activity_date)

        row = {
            "name": name,
            "activity_date": activity_date.isoformat(),
            "activity_type": join_activity_types(activity_types),
            "duration_min": int(duration_min),
            "mood_key": mood_key or None,
            "note": (note or "").strip() or None,
            "file_path": file_info["file_path"] if file_info else None,
            "file_name": file_info["file_name"] if file_info else None,
            "file_mime": file_info["file_mime"] if file_info else None,
            "file_size": file_info["file_size"] if file_info else None,
            # 统一使用 APP_TIMEZONE（旧版用服务器时区，会和统计对不上）
            "submitted_at": get_now_local().isoformat(),
        }
        insert_checkin(row)

        st.session_state["last_submit_fingerprint"] = fingerprint
        st.session_state["submit_recently_completed"] = True
        st.session_state["submit_in_progress"] = False
        st.session_state["submit_form_version"] += 1
        st.session_state["reset_submit_activity_types"] = True
        st.session_state["submit_success_message"] = "记录好了，辛苦！"
        st.rerun()

    except Exception as e:
        st.session_state["submit_in_progress"] = False
        st.error("提交失败。")
        st.exception(e)
