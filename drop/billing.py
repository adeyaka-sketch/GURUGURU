import functools
import os
import secrets
import string
import uuid
from datetime import datetime

from flask import jsonify, session

from .db import execute, query_one

PRICE_JPY = 980
PLAN_NAME = "GURUGURU Standard"

DEFAULT_MONTHLY_LIMIT = 50
TOPUP_JPY = 500
TOPUP_CREDITS = 30

# 未加入の訪問者でも、「会話させる」→「生まれた子を生み出す」の一連の流れを
# 一度は無料で体験できるよう、生涯2回までの無料お試し枠を設ける。
FREE_TRIAL_LIMIT = 2


def stripe_enabled():
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def get_stripe():
    import stripe

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    return stripe


def get_price_id():
    return os.environ.get("STRIPE_PRICE_ID")


def get_topup_price_id():
    return os.environ.get("STRIPE_TOPUP_PRICE_ID")


def get_webhook_secret():
    return os.environ.get("STRIPE_WEBHOOK_SECRET")


def generate_access_code():
    alphabet = string.ascii_uppercase + string.digits
    chunk = lambda: "".join(secrets.choice(alphabet) for _ in range(4))
    return f"GURUGURU-{chunk()}-{chunk()}"


def create_access_code(email, stripe_customer_id="", stripe_subscription_id="", monthly_limit=None):
    """
    アクセスコードを新規発行する。月額サブスク加入時は monthly_limit を省略して
    デフォルト(DEFAULT_MONTHLY_LIMIT)を使う。追加クレジット単体購入(サブスク未加入)の
    場合は monthly_limit=0 を渡し、無料の月間基本枠を持たせず購入したクレジット分だけ
    使えるようにする。
    """
    code = generate_access_code()
    if monthly_limit is None:
        monthly_limit = DEFAULT_MONTHLY_LIMIT
    execute(
        """INSERT INTO access_codes (code, email, stripe_customer_id, stripe_subscription_id, status, monthly_limit)
           VALUES (?, ?, ?, ?, 'active', ?)""",
        (code, email, stripe_customer_id, stripe_subscription_id, monthly_limit),
    )
    return code


def get_access_code(code):
    return query_one("SELECT * FROM access_codes WHERE code = ?", (code,))


def get_access_code_by_subscription(subscription_id):
    return query_one("SELECT * FROM access_codes WHERE stripe_subscription_id = ?", (subscription_id,))


def set_access_code_status(subscription_id, status):
    execute(
        "UPDATE access_codes SET status = ?, updated_at = datetime('now') WHERE stripe_subscription_id = ?",
        (status, subscription_id),
    )


def get_anon_id():
    """未加入セッションでも安定した識別子を持てるよう、ブラウザごとの匿名IDをCookieに保持する。
    個人情報は含まない。アクセス解析(drop/routes/analytics.py)とも共有する。"""
    if "anon_id" not in session:
        session["anon_id"] = uuid.uuid4().hex[:12]
        session.modified = True
    return session["anon_id"]


def current_creator_id():
    """このブラウザセッションを一意に識別するID。作成者タグに使う。
    有料会員はアクセスコード、未加入者(無料お試し含む)は匿名IDを使う。"""
    return session.get("access_code") or get_anon_id()


def is_paid_session():
    code = session.get("access_code")
    if not code:
        return False
    row = get_access_code(code)
    return bool(row and row["status"] == "active")


def _current_period():
    return datetime.now().strftime("%Y-%m")


def _ensure_period(row):
    """月が変わっていたら利用回数をリセットする。返り値は最新のusage_count。"""
    period = _current_period()
    if row["usage_period"] != period:
        execute(
            "UPDATE access_codes SET usage_count = 0, usage_period = ? WHERE code = ?",
            (period, row["code"]),
        )
        return 0
    return row["usage_count"]


def get_usage_status(code):
    """残り利用回数などを返す(UI表示用、消費はしない)。"""
    row = get_access_code(code)
    if not row:
        return None
    usage_count = _ensure_period(row)
    remaining_base = max(0, row["monthly_limit"] - usage_count)
    return {
        "monthlyLimit": row["monthly_limit"],
        "usageCount": usage_count,
        "remainingBase": remaining_base,
        "bonusCredits": row["bonus_credits"],
        "remainingTotal": remaining_base + row["bonus_credits"],
    }


def consume_usage(code):
    """
    1回分のAI呼び出しを消費する。月内上限→ボーナスクレジットの順で消費し、
    どちらも尽きていればFalseを返す(呼び出し元は403/429で弾く)。
    """
    row = get_access_code(code)
    if not row:
        return False
    usage_count = _ensure_period(row)

    if usage_count < row["monthly_limit"]:
        execute(
            "UPDATE access_codes SET usage_count = usage_count + 1 WHERE code = ?",
            (code,),
        )
        return True

    if row["bonus_credits"] > 0:
        execute(
            "UPDATE access_codes SET bonus_credits = bonus_credits - 1 WHERE code = ?",
            (code,),
        )
        return True

    return False


def add_bonus_credits(code, amount):
    execute(
        "UPDATE access_codes SET bonus_credits = bonus_credits + ? WHERE code = ?",
        (amount, code),
    )


def free_trial_remaining():
    """未加入セッションの、無料お試し残り回数(セッションCookieに保持)。"""
    used = session.get("free_trial_count", 0)
    return max(0, FREE_TRIAL_LIMIT - used)


def _consume_free_trial():
    used = session.get("free_trial_count", 0)
    if used >= FREE_TRIAL_LIMIT:
        return False
    session["free_trial_count"] = used + 1
    session.modified = True
    return True


def require_paid_access(view_func):
    """このAPIはClaude呼び出しなど実費が発生するため、有料アクセスコード+利用枠、
    または未加入者向けの無料お試し枠のいずれかが必要。"""

    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        if not stripe_enabled():
            # Stripe未設定の間(開発中)は素通しする
            return view_func(*args, **kwargs)

        code = session.get("access_code")
        if code and is_paid_session():
            if not consume_usage(code):
                return (
                    jsonify(
                        {
                            "error": f"今月のAI呼び出し上限({DEFAULT_MONTHLY_LIMIT}回)に達しました。"
                            f"追加クレジット(¥{TOPUP_JPY}で{TOPUP_CREDITS}回分)を購入するか、翌月まで待ってください。",
                            "usageExceeded": True,
                        }
                    ),
                    429,
                )
            return view_func(*args, **kwargs)

        if _consume_free_trial():
            return view_func(*args, **kwargs)

        return (
            jsonify(
                {
                    "error": "無料でお試しいただける回数(2回)を使い切りました。続きは有料プラン(月額980円)でご利用いただけます。",
                    "paywall": True,
                    "trialExhausted": True,
                }
            ),
            402,
        )

    return wrapper
