"""社区页：留言板（表情回应 + 文字回复）+ 运动相册。"""
from html import escape

import pandas as pd
import streamlit as st

from core.config import MESSAGE_REACTIONS, PRIMARY_ACTIVITY_SUFFIX, get_members
from core.db import (
    create_signed_image_url,
    get_now_local,
    get_reaction_count_map,
    get_supabase,
    increment_reaction,
    load_checkins,
)
from core.rules import activity_emoji
from ui.components import render_blue_table


# -----------------------------
# 留言回复（新增，需要 message_comments 表，见 README；没建表会优雅降级）
# -----------------------------

@st.cache_data(ttl=15)
def _load_comments() -> pd.DataFrame:
    try:
        response = (
            get_supabase()
            .table("message_comments")
            .select("*")
            .order("created_at", desc=False)
            .limit(2000)
            .execute()
        )
        df = pd.DataFrame(response.data if response and response.data else [])
        if not df.empty:
            df["checkin_id"] = (
                pd.to_numeric(df["checkin_id"], errors="coerce").fillna(0).astype(int)
            )
        return df
    except Exception:
        return pd.DataFrame()


def _insert_comment(checkin_id: int, author: str, content: str):
    get_supabase().table("message_comments").insert(
        {
            "checkin_id": int(checkin_id),
            "author": author.strip(),
            "content": content.strip(),
            "created_at": get_now_local().isoformat(),
        }
    ).execute()
    _load_comments.clear()


def _render_message_board(df_all: pd.DataFrame, max_cards: int = 80):
    st.caption("大家打卡时随手写下的运动碎碎念。")

    if df_all.empty or "note" not in df_all.columns:
        st.info("还没有留言。")
        return

    notes = df_all.copy()
    notes["note"] = notes["note"].fillna("").astype(str).str.strip()
    notes = notes[notes["note"] != ""].copy()
    if notes.empty:
        st.info("还没有人写备注。")
        return

    notes["activity_date_dt"] = pd.to_datetime(notes["activity_date"], errors="coerce")
    notes["submitted_at_dt"] = pd.to_datetime(notes["submitted_at"], errors="coerce")
    notes = (
        notes.sort_values(["activity_date_dt", "submitted_at_dt"], ascending=False)
        .head(max_cards)
        .reset_index(drop=True)
    )

    try:
        reaction_map = get_reaction_count_map()
    except Exception:
        reaction_map = {}
        st.warning("留言互动数据暂时读取失败，但留言仍可正常显示。")

    comments = _load_comments()
    comments_available = not comments.empty or _comments_table_exists()

    st.markdown(
        """
        <style>
        .message-card {
            border: 1px solid rgba(37, 99, 235, 0.14);
            border-radius: 18px;
            padding: 1rem 1.05rem;
            margin-bottom: 0.45rem;
            background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(234,242,255,0.92));
            box-shadow: 0 8px 22px rgba(37, 99, 235, 0.08);
        }
        .message-meta { color: #475569; font-size: 0.9rem; margin-bottom: 0.55rem; line-height: 1.55; }
        .message-name { font-weight: 700; color: #172033; }
        .message-note {
            color: #172033; font-size: 1.02rem; line-height: 1.75;
            white-space: pre-wrap; word-break: break-word;
        }
        .message-activity { color: #2563EB; }
        .comment-line { color: #475569; font-size: 0.88rem; line-height: 1.6; margin: 0.15rem 0; }
        .comment-line b { color: #1D4ED8; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    columns = st.columns(2)

    for idx, row in notes.iterrows():
        try:
            checkin_id = int(row.get("id", 0))
        except (TypeError, ValueError):
            checkin_id = 0

        name = escape(str(row.get("name", "")))
        date = escape(str(row.get("activity_date", "")))
        activity = escape(
            str(row.get("activity_type", "")).replace(PRIMARY_ACTIVITY_SUFFIX, "")
        )
        minutes = escape(str(row.get("duration_min", "")))
        note = escape(str(row.get("note", "")))
        emoji = activity_emoji(str(row.get("activity_type", "")))

        with columns[idx % 2]:
            st.markdown(
                f"""
                <div class="message-card">
                    <div class="message-meta">
                        <span style="font-size:1.25rem;">{emoji}</span>
                        <span class="message-name">{name}</span>
                        ｜ {date} ｜ <span class="message-activity">{activity}</span>
                        ｜ {minutes} 分钟
                    </div>
                    <div class="message-note">{note}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            reaction_cols = st.columns(len(MESSAGE_REACTIONS))
            for r_idx, (emoji_key, emoji_symbol, emoji_label) in enumerate(
                MESSAGE_REACTIONS
            ):
                count = reaction_map.get((checkin_id, emoji_key), 0)
                with reaction_cols[r_idx]:
                    if st.button(
                        f"{emoji_symbol} {count}",
                        help=emoji_label,
                        key=f"message_reaction_{checkin_id}_{emoji_key}_{idx}",
                        disabled=checkin_id <= 0,
                        use_container_width=True,
                    ):
                        try:
                            increment_reaction(checkin_id, emoji_key)
                            st.rerun()
                        except Exception as e:
                            st.error("回应失败，请稍后再试。")
                            st.exception(e)

            # 文字回复
            if comments_available and checkin_id > 0:
                card_comments = (
                    comments[comments["checkin_id"] == checkin_id]
                    if not comments.empty
                    else pd.DataFrame()
                )
                reply_label = (
                    f"💬 回复（{len(card_comments)}）"
                    if not card_comments.empty
                    else "💬 回复"
                )
                with st.expander(reply_label, expanded=False):
                    for _, c in card_comments.iterrows():
                        st.markdown(
                            f"<div class='comment-line'><b>{escape(str(c.get('author', '')))}"
                            f"</b>：{escape(str(c.get('content', '')))}</div>",
                            unsafe_allow_html=True,
                        )

                    members = get_members()
                    with st.form(f"comment_form_{checkin_id}_{idx}", clear_on_submit=True):
                        if members:
                            author = st.selectbox(
                                "我是", members, key=f"comment_author_{checkin_id}_{idx}"
                            )
                        else:
                            author = st.text_input(
                                "我是", key=f"comment_author_{checkin_id}_{idx}"
                            )
                        content = st.text_input(
                            "说点什么", key=f"comment_content_{checkin_id}_{idx}"
                        )
                        if st.form_submit_button("发送"):
                            if str(author).strip() and content.strip():
                                try:
                                    _insert_comment(checkin_id, str(author), content)
                                    st.rerun()
                                except Exception:
                                    st.error("回复失败，请稍后再试。")
                            else:
                                st.warning("名字和内容都要填一下。")

    if len(notes) >= max_cards:
        st.caption(f"这里展示最近 {max_cards} 条留言。更早的备注仍然保存在后台记录里。")


@st.cache_data(ttl=300)
def _comments_table_exists() -> bool:
    try:
        get_supabase().table("message_comments").select("id").limit(1).execute()
        return True
    except Exception:
        return False


# -----------------------------
# 相册
# -----------------------------

def _render_gallery(df_all: pd.DataFrame, limit: int = 12):
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

    left, mid, right = st.columns([1, 3, 1])
    with left:
        if st.button("← 上一张", use_container_width=True, key="gallery_prev"):
            st.session_state.gallery_index = (
                st.session_state.gallery_index - 1
            ) % len(gallery)
            st.rerun()
    with mid:
        st.markdown(
            f"<div style='text-align:center; color:#6b7280; padding-top:0.5rem;'>"
            f"{st.session_state.gallery_index + 1} / {len(gallery)}</div>",
            unsafe_allow_html=True,
        )
    with right:
        if st.button("下一张 →", use_container_width=True, key="gallery_next"):
            st.session_state.gallery_index = (
                st.session_state.gallery_index + 1
            ) % len(gallery)
            st.rerun()

    row = gallery.iloc[st.session_state.gallery_index]

    # 签名链接已在 db 层缓存 30 分钟，翻页不再重复请求 Storage API
    try:
        signed_url = create_signed_image_url(str(row.get("file_path", "")).strip())
    except Exception:
        signed_url = None

    caption = (
        f"{row.get('name', '')} ｜ {row.get('activity_date', '')} ｜ "
        f"{row.get('activity_type', '')} ｜ {row.get('duration_min', '')} 分钟"
    )

    st.markdown(
        """
        <style>
        .gallery-frame {
            border-radius: 22px;
            border: 1px solid rgba(37, 99, 235, 0.14);
            padding: 0.8rem;
            background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(234,242,255,0.92));
            box-shadow: 0 12px 28px rgba(37, 99, 235, 0.09);
            margin-top: 0.5rem; margin-bottom: 1rem;
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
            try:
                thumb_url = create_signed_image_url(
                    str(item.get("file_path", "")).strip()
                )
            except Exception:
                thumb_url = None
            if thumb_url:
                st.image(thumb_url, use_container_width=True)
            if st.button(
                f"{i + 1}. {item.get('name', '')}",
                key=f"gallery_thumb_{i}",
                use_container_width=True,
            ):
                st.session_state.gallery_index = i
                st.rerun()

    with st.expander("查看图片对应记录"):
        display_cols = [
            c
            for c in ["name", "activity_date", "activity_type", "duration_min", "note", "submitted_at"]
            if c in gallery.columns
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
        render_blue_table(records)


def community_page():
    st.subheader("社区")

    try:
        df_all = load_checkins()
    except Exception as e:
        st.error("读取记录失败。")
        st.exception(e)
        return

    tab_messages, tab_gallery = st.tabs(["留言板", "运动相册"])
    with tab_messages:
        _render_message_board(df_all)
    with tab_gallery:
        _render_gallery(df_all, limit=12)
