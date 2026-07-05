"""规则层单元测试。

运行：python -m pytest tests/ 或直接 python tests/test_rules.py
不依赖真实 Streamlit / Supabase（自动注入桩模块），改规则前后跑一遍可防翻车。
"""
import sys
import types
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---- streamlit 桩：core.config 只用到 st.secrets.get ----
if "streamlit" not in sys.modules:
    stub = types.ModuleType("streamlit")

    class _Secrets(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    stub.secrets = _Secrets()

    def _passthrough_decorator(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def wrap(fn):
            fn.clear = lambda: None
            return fn

        return wrap

    stub.cache_data = _passthrough_decorator
    stub.cache_resource = _passthrough_decorator
    sys.modules["streamlit"] = stub

import pandas as pd  # noqa: E402

from core.rules import (  # noqa: E402
    compute_day_streak,
    format_goal_credit,
    get_member_monthly_target_checkins,
    is_half_credit_activity,
    join_activity_types,
    join_mood_values,
    split_activity_types,
    split_mood_keys,
    summarize_goal_credits,
)


def _df(rows):
    return pd.DataFrame(rows)


def test_split_activity_types():
    assert split_activity_types("跑步、力量训练") == ["跑步", "力量训练"]
    assert split_activity_types("跑步（主要）,散步") == ["跑步", "散步"]
    assert split_activity_types(["跑步", "跑步", "游泳"]) == ["跑步", "游泳"]
    assert split_activity_types("") == []
    assert split_activity_types(None) == []
    assert join_activity_types("跑步/游泳") == "跑步、游泳"


def test_half_credit_detection():
    assert is_half_credit_activity("散步") is True
    assert is_half_credit_activity("散步、台球") is True
    assert is_half_credit_activity("散步、跑步") is False
    assert is_half_credit_activity("跑步") is False
    assert is_half_credit_activity("") is False


def test_mood_parsing():
    assert split_mood_keys("happy、relaxed") == ["happy", "relaxed"]
    assert join_mood_values(["happy"], "🔥", "充满power") == "happy、custom:🔥 充满power"
    assert join_mood_values([], "", "") is None


def test_summarize_same_day_dedup():
    """同一天多条普通记录只计 1 次有效运动。"""
    df = _df(
        [
            {"id": 1, "name": "A", "activity_date": date(2026, 6, 1),
             "activity_type": "跑步", "duration_min": 40},
            {"id": 2, "name": "A", "activity_date": date(2026, 6, 1),
             "activity_type": "游泳", "duration_min": 50},
            {"id": 3, "name": "A", "activity_date": date(2026, 6, 2),
             "activity_type": "跑步", "duration_min": 30},
        ]
    )
    out = summarize_goal_credits(df, ["name"], target_minutes=30)
    row = out.iloc[0]
    assert row["总打卡次数"] == 3
    assert row["有效运动次数"] == 2.0  # 两个不同的天
    assert row["半次运动达标记录数"] == 0


def test_summarize_half_credit_day():
    """当天只有半次类型 → 0.5；同天多条半次仍是 0.5。"""
    df = _df(
        [
            {"id": 1, "name": "A", "activity_date": date(2026, 6, 1),
             "activity_type": "散步", "duration_min": 30},
            {"id": 2, "name": "A", "activity_date": date(2026, 6, 1),
             "activity_type": "台球", "duration_min": 60},
        ]
    )
    out = summarize_goal_credits(df, ["name"], target_minutes=30)
    row = out.iloc[0]
    assert row["有效运动次数"] == 0.5
    assert row["半次运动达标记录数"] == 1


def test_summarize_normal_beats_half_same_day():
    """同一天既有普通又有半次达标记录 → 按 1 次普通计入。"""
    df = _df(
        [
            {"id": 1, "name": "A", "activity_date": date(2026, 6, 1),
             "activity_type": "散步", "duration_min": 30},
            {"id": 2, "name": "A", "activity_date": date(2026, 6, 1),
             "activity_type": "跑步", "duration_min": 30},
        ]
    )
    out = summarize_goal_credits(df, ["name"], target_minutes=30)
    row = out.iloc[0]
    assert row["有效运动次数"] == 1.0
    assert row["半次运动达标记录数"] == 0


def test_summarize_duration_threshold():
    """时长不足 target_minutes 的记录不计入有效次数。"""
    df = _df(
        [
            {"id": 1, "name": "A", "activity_date": date(2026, 6, 1),
             "activity_type": "跑步", "duration_min": 20},
        ]
    )
    out = summarize_goal_credits(df, ["name"], target_minutes=30)
    assert out.iloc[0]["有效运动次数"] == 0.0


def test_half_credit_cap():
    """半次记录最多计入 8 条 = 4 次有效运动。"""
    rows = [
        {"id": i, "name": "A", "activity_date": date(2026, 6, i),
         "activity_type": "散步", "duration_min": 30}
        for i in range(1, 13)  # 12 个不同的天，全是半次
    ]
    out = summarize_goal_credits(_df(rows), ["name"], target_minutes=30)
    row = out.iloc[0]
    assert row["半次运动达标记录数"] == 12
    assert row["半次运动计入次数"] == 4.0  # cap 8 × 0.5
    assert row["有效运动次数"] == 4.0


def test_gender_targets():
    assert get_member_monthly_target_checkins("王平") == 7   # 女
    assert get_member_monthly_target_checkins("赵阳") == 8   # 男
    assert get_member_monthly_target_checkins("未知的人") == 8


def test_format_goal_credit():
    assert format_goal_credit(3.0) == "3"
    assert format_goal_credit(2.5) == "2.5"
    assert format_goal_credit(0.5) == "0.5"


def test_day_streak():
    days = {date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 5)}
    current, longest = compute_day_streak(days, date(2026, 6, 5))
    assert current == 1
    assert longest == 3
    # 今天没打卡但昨天打了 → 连续不清零
    current2, _ = compute_day_streak(days, date(2026, 6, 6))
    assert current2 == 1
    # 断了两天 → 清零
    current3, _ = compute_day_streak(days, date(2026, 6, 8))
    assert current3 == 0


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {name}: {e}")
    sys.exit(1 if failures else 0)
