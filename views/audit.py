"""监督页：随机抽查 + 抽查结果记录（新增闭环）。"""
import pandas as pd
import streamlit as st

from core.config import PRIMARY_ACTIVITY_SUFFIX, get_members
from core.db import (
    create_signed_image_url,
    get_now_local,
    insert_audit_log,
    load_audit_logs,
    load_checkins,
)
from core.rules import format_mood_key
from ui.components import render_blue_table


def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in ["nan", "none", "nat"] else text


def _time_value(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            pass
    return str(value)


def audit_page():
    st.subheader("我要监督！")
    st.caption(
        "随机抽取一条带照片的打卡记录，核对：照片、运动类型、时长、备注是否大体相符。"
        "核对完可以记录一个结果，让抽查形成闭环。"
    )

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取记录失败。")
        st.exception(e)
        return

    if df_all.empty:
        st.info("还没有记录可监督。")
        return
    if "file_path" not in df_all.columns:
        st.info("当前记录里没有图片字段，暂时无法监督照片。")
        return

    audit_df = df_all.copy()
    audit_df["file_path"] = audit_df["file_path"].fillna("").astype(str).str.strip()
    audit_df = audit_df[audit_df["file_path"] != ""].copy()
    if audit_df.empty:
        st.info("还没有带照片的记录可监督。")
        return
    if "id" not in audit_df.columns:
        st.warning("记录缺少 ID 字段，暂时无法稳定随机抽查。")
        return

    audit_df["_audit_id"] = pd.to_numeric(audit_df["id"], errors="coerce")
    audit_df = audit_df.dropna(subset=["_audit_id"]).copy()
    if audit_df.empty:
        st.info("没有可识别 ID 的记录可监督。")
        return
    audit_df["_audit_id"] = audit_df["_audit_id"].astype(int)
    valid_ids = audit_df["_audit_id"].tolist()

    c1, c2 = st.columns([1, 2])
    with c1:
        random_clicked = st.button(
            "🎲 随机抽一条", type="primary", use_container_width=True,
            key="audit_random_pick",
        )
    with c2:
        st.caption(f"当前可抽查记录：{len(audit_df)} 条。只抽取带照片的记录。")

    current_id = st.session_state.get("audit_selected_record_id")
    if random_clicked or current_id not in valid_ids:
        selected_id = int(audit_df.sample(n=1).iloc[0]["_audit_id"])
        st.session_state["audit_selected_record_id"] = selected_id
    else:
        selected_id = int(current_id)

    selected = audit_df[audit_df["_audit_id"] == selected_id]
    if selected.empty:
        st.info("这条记录可能已经被删除，请重新抽取。")
        return
    row = selected.iloc[0]

    file_path = _clean(row.get("file_path"))
    signed_url = None
    try:
        signed_url = create_signed_image_url(file_path)
    except Exception:
        st.warning("图片临时链接生成失败，但记录信息仍可查看。")

    image_col, info_col = st.columns([1.15, 1])

    with image_col:
        st.markdown("#### 抽查照片")
        if signed_url:
            st.image(
                signed_url,
                caption=f"{_clean(row.get('name'))} ｜ {_clean(row.get('activity_date'))}",
                use_container_width=True,
            )
            if hasattr(st, "link_button"):
                st.link_button("打开图片原图", signed_url, use_container_width=True)
        else:
            st.warning("这条记录的图片暂时无法显示。")

    with info_col:
        st.markdown("#### 抽查记录")
        mood_text = (
            format_mood_key(row.get("mood_key")) if "mood_key" in row.index else "未记录"
        )
        record_view = pd.DataFrame(
            [
                {
                    "记录ID": int(row.get("_audit_id")),
                    "姓名": _clean(row.get("name")),
                    "运动日期": _clean(row.get("activity_date")),
                    "运动类型": _clean(row.get("activity_type")).replace(
                        PRIMARY_ACTIVITY_SUFFIX, ""
                    ),
                    "运动时长": f"{_clean(row.get('duration_min'))} 分钟",
                    "运动后心情": mood_text,
                    "碎碎念": _clean(row.get("note")) or "—",
                    "提交时间": _time_value(row.get("submitted_at")) or "—",
                    "图片文件名": _clean(row.get("file_name")) or "—",
                }
            ]
        )
        render_blue_table(record_view)

    st.info(
        "监督原则：只判断是否明显不相符。比如照片完全不是运动截图/运动照片、"
        "时长和截图明显冲突、运动类型明显对不上。不要因为截图格式不同就误伤。"
    )

    # ---- 抽查结果记录（新增） ----
    st.markdown("#### 记录抽查结果")

    audit_logs = load_audit_logs()
    logs_available = isinstance(audit_logs, pd.DataFrame) and (
        not audit_logs.empty or _logs_table_ok()
    )

    if not logs_available:
        st.caption(
            "提示：还没有创建 audit_logs 表，抽查结果暂时无法保存。"
            "建表 SQL 见项目 README。"
        )
        return

    members = get_members()
    with st.form(f"audit_result_form_{selected_id}", clear_on_submit=True):
        if members:
            auditor = st.selectbox("监督人", members)
        else:
            auditor = st.text_input("监督人")

        result = st.radio(
            "核对结果",
            ["✅ 相符", "⚠️ 存疑"],
            horizontal=True,
        )
        note = st.text_input("备注（存疑时建议写明原因）")

        if st.form_submit_button("保存抽查结果", type="primary"):
            try:
                insert_audit_log(
                    selected_id,
                    str(auditor),
                    "ok" if result.startswith("✅") else "flagged",
                    note,
                )
                st.success("已记录。感谢监督！")
            except Exception as e:
                st.error("保存失败。")
                st.exception(e)

    # ---- 抽查历史 ----
    if not audit_logs.empty:
        with st.expander(f"抽查历史（最近 {len(audit_logs)} 条）"):
            logs_view = audit_logs.copy()
            logs_view["result"] = logs_view["result"].map(
                {"ok": "✅ 相符", "flagged": "⚠️ 存疑"}
            ).fillna(logs_view["result"])

            # 关联被抽查记录的姓名/日期，方便阅读
            join_cols = df_all[["id", "name", "activity_date"]].rename(
                columns={"id": "checkin_id"}
            )
            logs_view = logs_view.merge(join_cols, on="checkin_id", how="left")

            display_cols = [
                c for c in [
                    "created_at", "auditor", "result", "name",
                    "activity_date", "checkin_id", "note",
                ]
                if c in logs_view.columns
            ]
            logs_view = logs_view[display_cols].rename(
                columns={
                    "created_at": "抽查时间",
                    "auditor": "监督人",
                    "result": "结果",
                    "name": "被抽查人",
                    "activity_date": "运动日期",
                    "checkin_id": "记录ID",
                    "note": "备注",
                }
            )
            render_blue_table(logs_view)

            flagged = audit_logs[audit_logs["result"] == "flagged"]
            if not flagged.empty:
                st.caption(f"⚠️ 目前有 {len(flagged)} 条存疑记录，可在后台核实处理。")


@st.cache_data(ttl=300)
def _logs_table_ok() -> bool:
    from core.db import get_supabase

    try:
        get_supabase().table("audit_logs").select("id").limit(1).execute()
        return True
    except Exception:
        return False
