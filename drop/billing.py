import functools
import os
import secrets
import string

from flask import jsonify, session

from .db import execute, query_one

PRICE_JPY = 980
PLAN_NAME = "GURUGURU Standard"


def stripe_enabled():
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def get_stripe():
    import stripe

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    return stripe


def get_price_id():
    return os.environ.get("STRIPE_PRICE_ID")


def get_webhook_secret():
    return os.environ.get("STRIPE_WEBHOOK_SECRET")


def generate_access_code():
    alphabet = string.ascii_uppercase + string.digits
    chunk = lambda: "".join(secrets.choice(alphabet) for _ in range(4))
    return f"GURUGURU-{chunk()}-{chunk()}"


def create_access_code(email, stripe_customer_id="", stripe_subscription_id=""):
    code = generate_access_code()
    execute(
        """INSERT INTO access_codes (code, email, stripe_customer_id, stripe_subscription_id, status)
           VALUES (?, ?, ?, ?, 'active')""",
        (code, email, stripe_customer_id, stripe_subscription_id),
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


def current_creator_id():
    """このブラウザセッションを一意に識別するID(=支払い済みアクセスコード)。作成者タグに使う。"""
    return session.get("access_code")


def is_paid_session():
    code = session.get("access_code")
    if not code:
        return False
    row = get_access_code(code)
    return bool(row and row["status"] == "active")


def require_paid_access(view_func):
    """このAPIはClaude呼び出しなど実費が発生するため、有料アクセスコードが必要。"""

    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        if not stripe_enabled():
            # Stripe未設定の間(開発中)は素通しする
            return view_func(*args, **kwargs)
        if not is_paid_session():
            return (
                jsonify(
                    {
                        "error": "この機能は有料プラン(月額980円)が必要です。",
                        "paywall": True,
                    }
                ),
                402,
            )
        return view_func(*args, **kwargs)

    return wrapper
