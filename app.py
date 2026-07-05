"""实验室运动打卡 · 入口。

重构要点：
- st.navigation 多页面：只执行当前页面，告别九个 tab 全量重算；
- 页面收敛为 6 个入口：打卡 / 我的 / 看板 / 社区 / 评选 / 监督 / 后台；
- 统一样式 token、缓存签名链接、修复 NameError 与时区问题。
"""
import hmac

import streamlit as st

st.set_page_config(
    page_title="实验室运动打卡",
    page_icon="🏃",
    layout="wide",
)

from ui.style import inject_app_style  # noqa: E402

inject_app_style()

# -----------------------------
# 邀请码门禁
# -----------------------------

if "invite_ok" not in st.session_state:
    st.session_state.invite_ok = False

if not st.session_state.invite_ok:
    st.title("实验室运动记录")
    st.caption("输入邀请码进入。")

    invite_code = st.text_input("邀请码", type="password")
    if st.button("进入打卡", type="primary"):
        if hmac.compare_digest(str(invite_code), str(st.secrets["INVITE_CODE"])):
            st.session_state.invite_ok = True
            st.rerun()
        else:
            st.error("邀请码不对。")
    st.stop()

# -----------------------------
# 多页面导航（登录后才加载视图）
# -----------------------------

from views.admin import admin_page  # noqa: E402
from views.audit import audit_page  # noqa: E402
from views.checkin import checkin_page  # noqa: E402
from views.community import community_page  # noqa: E402
from views.dashboard import dashboard_page  # noqa: E402
from views.me import me_page  # noqa: E402
from views.selection import selection_page  # noqa: E402

pages = {
    "记录": [
        st.Page(checkin_page, title="打卡", icon="🏃", url_path="checkin", default=True),
        st.Page(me_page, title="我的", icon="🙋", url_path="me"),
    ],
    "看板": [
        st.Page(dashboard_page, title="运动看板", icon="📊", url_path="dashboard"),
        st.Page(community_page, title="社区", icon="💬", url_path="community"),
    ],
    "评选与管理": [
        st.Page(selection_page, title="评选", icon="🏆", url_path="selection"),
        st.Page(audit_page, title="我要监督！", icon="🔍", url_path="audit"),
        st.Page(admin_page, title="后台", icon="🔧", url_path="admin"),
    ],
}

navigation = st.navigation(pages)
navigation.run()
