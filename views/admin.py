"""后台页：筛选、批量导出/删除、单条修改/删除。"""
import hmac

import pandas as pd
import streamlit as st

from core.config import ACTIVITY_TYPES, MAX_SOURCE_UPLOAD_MB, MIN_SUBMIT_MINUTES, get_members
from core.db import (
    create_signed_image_url,
    delete_checkins,
    get_now_local,
    get_supabase,
    update_checkin,
)
from core.images import upload_image
from core.rules import join_activity_types, split_activity_types


def check_password(input_value: str, secret_value: str) -> bool:
    return hmac.compare_digest(str(input_value), str(secret_value))


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
    except (TypeError, ValueError):
        return default


def _export_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def admin_page():
    st.subheader("后台")

    admin_password = st.text_input("管理员密码", type="password")
    if not check_password(admin_password, st.secrets["ADMIN_PASSWORD"]):
        st.info("输入密码后查看完整记录。")
        return

    try:
        response = (
            get_supabase()
            .table("exercise_checkins")
            .select("*")
            .order("submitted_at", desc=True)
            .execute()
        )
        df = pd.DataFrame(response.data)
    except Exception as e:
        st.error("后台读取失败。")
        st.exception(e)
        return

    if df.empty:
        st.info("还没有记录。")
        return

    df["activity_date"] = pd.to_datetime(df["activity_date"], errors="coerce").dt.date
    df["submitted_at"] = pd.to_datetime(df["submitted_at"], errors="coerce")
    df["duration_min"] = (
        pd.to_numeric(df["duration_min"], errors="coerce").fillna(0).astype(int)
    )

    # ---- 筛选 ----
    st.markdown("### 筛选")
    f1, f2, f3 = st.columns(3)

    with f1:
        all_names = sorted(df["name"].dropna().astype(str).unique().tolist())
        selected_names = st.multiselect("姓名", all_names, default=[], placeholder="全部")

    with f2:
        all_types = sorted(
            {
                a
                for v in df["activity_type"].dropna().astype(str).tolist()
                for a in split_activity_types(v)
            }
        )
        selected_types = st.multiselect("运动类型", all_types, default=[], placeholder="全部")

    with f3:
        valid_dates = df["activity_date"].dropna()
        if valid_dates.empty:
            default_range = (get_now_local().date(), get_now_local().date())
        else:
            default_range = (valid_dates.min(), valid_dates.max())
        selected_range = st.date_input("日期范围", value=default_range)

    filtered = df.copy()
    if selected_names:
        filtered = filtered[filtered["name"].isin(selected_names)]
    if selected_types:
        type_set = set(selected_types)
        filtered = filtered[
            filtered["activity_type"].apply(
                lambda v: bool(type_set & set(split_activity_types(v)))
            )
        ]
    if isinstance(selected_range, tuple) and len(selected_range) == 2:
        start_date, end_date = selected_range
        filtered = filtered[
            (filtered["activity_date"] >= start_date)
            & (filtered["activity_date"] <= end_date)
        ]

    filtered = filtered.sort_values("submitted_at", ascending=False)
    st.caption(f"当前筛选：{len(filtered)} 条记录")

    st.divider()

    # ---- 批量导出 ----
    st.markdown("### 批量导出")
    st.download_button(
        "导出当前筛选 CSV",
        data=_export_csv(filtered),
        file_name="exercise_checkins_filtered.csv",
        mime="text/csv",
        disabled=filtered.empty,
    )

    st.divider()

    # ---- 批量选择 ----
    st.markdown("### 批量选择")

    rename_map = {
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

    batch_view = filtered.copy()
    batch_view.insert(0, "选择", False)
    batch_view = batch_view[
        ["选择", "id", "name", "activity_date", "activity_type",
         "duration_min", "note", "submitted_at", "file_name", "file_path"]
    ].rename(columns=rename_map)

    edited = st.data_editor(
        batch_view,
        use_container_width=True,
        hide_index=True,
        disabled=[v for v in rename_map.values()],
        column_config={
            "选择": st.column_config.CheckboxColumn(
                "选择", help="勾选后可批量导出或删除。", default=False
            )
        },
        key="batch_record_selector",
    )

    selected_ids = (
        edited.loc[edited["选择"], "ID"].dropna().astype(int).tolist()
    )
    selected_df = filtered[filtered["id"].isin(selected_ids)].copy()
    st.caption(f"已选择：{len(selected_df)} 条")

    b1, b2 = st.columns(2)
    with b1:
        st.download_button(
            "导出勾选记录 CSV",
            data=_export_csv(selected_df),
            file_name="exercise_checkins_selected.csv",
            mime="text/csv",
            disabled=selected_df.empty,
        )
    with b2:
        confirm_batch = st.checkbox(
            f"确认删除已勾选的 {len(selected_df)} 条记录",
            disabled=selected_df.empty,
            key="confirm_batch_delete",
        )
        batch_delete = st.button(
            "批量删除勾选记录",
            type="secondary",
            disabled=selected_df.empty or not confirm_batch,
            key="batch_delete_records",
        )

    if batch_delete:
        try:
            ids = selected_df["id"].dropna().astype(int).tolist()
            paths = [
                _clean_text(x)
                for x in selected_df.get("file_path", pd.Series(dtype=str)).tolist()
                if _clean_text(x)
            ]
            delete_checkins(ids, paths)
            st.success(f"已删除 {len(selected_df)} 条记录。")
            st.rerun()
        except Exception as e:
            st.error("批量删除失败。")
            st.exception(e)

    st.divider()

    # ---- 单条修改 ----
    st.markdown("### 单条修改")

    edit_source = filtered if not filtered.empty else df
    options = [
        f"{r['id']} | {r['name']} | {r['activity_date']} | "
        f"{r['activity_type']} | {r['duration_min']} 分钟"
        for _, r in edit_source.iterrows()
    ]
    if not options:
        st.info("当前筛选下没有可修改的记录。")
        return

    selected_option = st.selectbox("选择记录", options)
    selected_id = int(selected_option.split("|")[0].strip())
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

        members = get_members()
        current_name = _clean_text(selected_row.get("name"))
        name_options = members.copy()
        if current_name and current_name not in name_options:
            name_options = [current_name] + name_options
        if not name_options:
            name_options = [current_name] if current_name else [""]

        current_activity_types = split_activity_types(
            _clean_text(selected_row.get("activity_type"))
        )
        activity_options = [
            a for a in current_activity_types if a not in ACTIVITY_TYPES
        ] + list(ACTIVITY_TYPES)

        current_date = pd.to_datetime(selected_row.get("activity_date"), errors="coerce")
        current_date = (
            get_now_local().date() if pd.isna(current_date) else current_date.date()
        )
        current_duration = _safe_int(selected_row.get("duration_min"), 30)
        current_note = _clean_text(selected_row.get("note"))

        with st.form(f"edit_record_form_{selected_id}"):
            edited_name = st.selectbox(
                "姓名",
                name_options,
                index=name_options.index(current_name)
                if current_name in name_options
                else 0,
            )
            edited_date = st.date_input("运动日期", value=current_date)
            edited_activities = st.multiselect(
                "运动类型（可多选）",
                activity_options,
                default=[a for a in current_activity_types if a in activity_options],
                help="可以选择多个运动类型，保存后会用顿号连接。",
            )
            edited_duration = st.number_input(
                "运动时长（分钟）",
                min_value=MIN_SUBMIT_MINUTES,
                max_value=600,
                value=max(current_duration, MIN_SUBMIT_MINUTES),
                step=5,
            )
            edited_note = st.text_area("今天有什么想说的？", value=current_note)
            replacement_file = st.file_uploader(
                f"替换截图或照片（可选，原图不超过 {MAX_SOURCE_UPLOAD_MB} MB，系统会自动压缩）",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=False,
                key=f"replacement_file_{selected_id}",
            )
            save_clicked = st.form_submit_button("保存修改")

        if save_clicked:
            if not edited_activities:
                st.error("请选择至少一种运动类型。")
                return
            try:
                update_row = {
                    "name": edited_name.strip(),
                    "activity_date": edited_date.isoformat(),
                    "activity_type": join_activity_types(edited_activities),
                    "duration_min": int(edited_duration),
                    "note": edited_note.strip() or None,
                }
                old_file_path = current_file_path

                if replacement_file is not None:
                    new_file_info = upload_image(
                        replacement_file, edited_name.strip(), edited_date
                    )
                    update_row.update(
                        {
                            "file_path": new_file_info["file_path"],
                            "file_name": new_file_info["file_name"],
                            "file_mime": new_file_info["file_mime"],
                            "file_size": new_file_info["file_size"],
                        }
                    )

                update_checkin(selected_id, update_row)

                if replacement_file is not None and old_file_path:
                    try:
                        from core.config import BUCKET_NAME

                        get_supabase().storage.from_(BUCKET_NAME).remove(
                            [old_file_path]
                        )
                    except Exception:
                        st.warning("记录已修改，但旧图片删除失败。可稍后手动清理。")

                st.success("已保存。")
                st.rerun()
            except Exception as e:
                st.error("保存失败。")
                st.exception(e)

    st.divider()

    # ---- 单条删除 ----
    st.markdown("### 单条删除")
    st.warning("删除会同时删除数据库记录和对应图片。这个操作不能撤回。")

    confirm_delete = st.checkbox(
        f"确认删除 ID {selected_id} 这条记录", key=f"confirm_delete_{selected_id}"
    )
    if st.button(
        "删除这条记录",
        type="secondary",
        disabled=not confirm_delete,
        key=f"delete_record_{selected_id}",
    ):
        try:
            record = df[df["id"] == selected_id].copy()
            ids = record["id"].dropna().astype(int).tolist()
            paths = [
                _clean_text(x)
                for x in record.get("file_path", pd.Series(dtype=str)).tolist()
                if _clean_text(x)
            ]
            delete_checkins(ids, paths)
            st.success("已删除。")
            st.rerun()
        except Exception as e:
            st.error("删除失败。")
            st.exception(e)
