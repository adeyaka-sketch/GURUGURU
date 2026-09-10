import os
from datetime import datetime

from flask import Blueprint, jsonify, redirect, request, session

from ..billing import (
    DEFAULT_MONTHLY_LIMIT,
    FREE_TRIAL_LIMIT,
    PRICE_JPY,
    TOPUP_CREDITS,
    TOPUP_JPY,
    add_bonus_credits,
    create_access_code,
    free_trial_remaining,
    get_access_code,
    get_access_code_by_subscription,
    get_price_id,
    get_stripe,
    get_topup_price_id,
    get_usage_status,
    get_webhook_secret,
    is_paid_session,
    set_access_code_status,
    stripe_enabled,
)

bp = Blueprint("billing", __name__)


def _period_end_text(subscription):
    """
    current_period_end は、Stripeのアカウント/APIバージョンによって
    Subscription直下にある場合と、items.data[0]配下にある場合がある。
    両方に対応し、日本語の日付文字列にして返す(取得できなければNone)。
    """
    timestamp = None
    try:
        timestamp = subscription["current_period_end"]
    except (KeyError, TypeError):
        try:
            timestamp = subscription["items"]["data"][0]["current_period_end"]
        except (KeyError, IndexError, TypeError):
            timestamp = None
    if not timestamp:
        return None
    return datetime.utcfromtimestamp(timestamp).strftime("%Y年%m月%d日")


@bp.get("/api/billing/status")
def status():
    code = session.get("access_code")
    usage = get_usage_status(code) if code else None
    paid = is_paid_session()
    return jsonify(
        {
            "enabled": stripe_enabled(),
            "paid": paid,
            "priceJpy": PRICE_JPY,
            "monthlyLimit": DEFAULT_MONTHLY_LIMIT,
            "topupJpy": TOPUP_JPY,
            "topupCredits": TOPUP_CREDITS,
            "usage": usage,
            "freeTrialLimit": FREE_TRIAL_LIMIT,
            "freeTrialRemaining": None if paid else free_trial_remaining(),
        }
    )


@bp.post("/api/billing/checkout")
def create_checkout():
    if not stripe_enabled():
        return jsonify({"error": "課金機能はまだ設定されていません。"}), 400

    stripe = get_stripe()
    base_url = request.host_url.rstrip("/")
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": get_price_id(), "quantity": 1}],
            success_url=f"{base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/billing/cancel",
        )
        return jsonify({"url": checkout_session.url})
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.get("/billing/success")
def checkout_success():
    session_id = request.args.get("session_id")
    if not session_id:
        return "決済情報が見つかりません。", 400

    stripe = get_stripe()
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        email = checkout_session.customer_details.email if checkout_session.customer_details else ""
        customer_id = checkout_session.customer
        subscription_id = checkout_session.subscription

        existing = get_access_code_by_subscription(subscription_id) if subscription_id else None
        if existing:
            code = existing["code"]
        else:
            code = create_access_code(email, customer_id or "", subscription_id or "")

        session["access_code"] = code

        return f"""
        <html><head><meta charset="utf-8"><title>お支払い完了</title>
        <style>body{{font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 20px;line-height:1.8}}
        .code{{background:#f2e3d5;padding:16px;border-radius:8px;font-size:20px;font-weight:bold;text-align:center;letter-spacing:0.05em}}</style>
        </head><body>
        <h2>お支払いありがとうございます</h2>
        <p>このブラウザでは、もう有料機能が使えます。別のブラウザ・端末で使う場合は、下記のアクセスコードを保管して「コードを入力」欄に貼り付けてください。</p>
        <div class="code">{code}</div>
        <p><a href="/">アプリに戻る</a></p>
        </body></html>
        """
    except Exception as err:  # noqa: BLE001
        return f"決済の確認中にエラーが発生しました: {err}", 500


@bp.get("/billing/cancel")
def checkout_cancel():
    return redirect("/")


@bp.post("/api/billing/topup-checkout")
def create_topup_checkout():
    """追加クレジット(¥500で30回分)の購入。既に有料会員であることが前提。"""
    if not stripe_enabled():
        return jsonify({"error": "課金機能はまだ設定されていません。"}), 400
    if not is_paid_session():
        return jsonify({"error": "先に月額プランへの加入が必要です。"}), 402

    stripe = get_stripe()
    base_url = request.host_url.rstrip("/")
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": get_topup_price_id(), "quantity": 1}],
            success_url=f"{base_url}/billing/topup-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/billing/cancel",
        )
        return jsonify({"url": checkout_session.url})
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.get("/billing/topup-success")
def topup_success():
    session_id = request.args.get("session_id")
    code = session.get("access_code")
    if not session_id or not code:
        return "決済情報、またはログイン状態が見つかりません。", 400

    stripe = get_stripe()
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        if checkout_session.payment_status == "paid":
            add_bonus_credits(code, TOPUP_CREDITS)

        return f"""
        <html><head><meta charset="utf-8"><title>追加クレジット購入完了</title>
        <style>body{{font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 20px;line-height:1.8}}</style>
        </head><body>
        <h2>追加クレジットを購入しました</h2>
        <p>{TOPUP_CREDITS}回分のAI呼び出し枠が追加されました。</p>
        <p><a href="/">アプリに戻る</a></p>
        </body></html>
        """
    except Exception as err:  # noqa: BLE001
        return f"決済の確認中にエラーが発生しました: {err}", 500


@bp.post("/api/billing/redeem")
def redeem():
    body = request.get_json(force=True) or {}
    code = (body.get("code") or "").strip().upper()
    row = get_access_code(code)
    if not row or row["status"] != "active":
        return jsonify({"error": "コードが無効か、有効期限が切れています。"}), 400
    session["access_code"] = code
    return jsonify({"ok": True})


@bp.post("/api/billing/cancel")
def cancel_subscription():
    """
    サブスクリプションを解約する(ユーザー自身の操作で完結させる自己解約フロー)。
    即時停止ではなく、現在のお支払い期間の終了時に自動更新を止める(cancel_at_period_end)。
    期間終了時にStripeから届く customer.subscription.deleted / updated Webhookで、
    access_codes.status が実際に "cancelled" に更新される。
    """
    if not stripe_enabled():
        return jsonify({"error": "課金機能はまだ設定されていません。"}), 400

    code = session.get("access_code")
    if not code or not is_paid_session():
        return jsonify({"error": "有料プランに加入していません。"}), 400

    row = get_access_code(code)
    subscription_id = row["stripe_subscription_id"] if row else ""
    if not subscription_id:
        return jsonify({"error": "サブスクリプション情報が見つかりませんでした。お手数ですが運営までお問い合わせください。"}), 400

    stripe = get_stripe()
    try:
        subscription = stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        period_end = _period_end_text(subscription)
        return jsonify({"ok": True, "cancelAtPeriodEnd": True, "periodEnd": period_end})
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.post("/api/billing/resume")
def resume_subscription():
    """解約予約(cancel_at_period_end)を取り消し、自動更新を再開する。"""
    if not stripe_enabled():
        return jsonify({"error": "課金機能はまだ設定されていません。"}), 400

    code = session.get("access_code")
    if not code or not is_paid_session():
        return jsonify({"error": "有料プランに加入していません。"}), 400

    row = get_access_code(code)
    subscription_id = row["stripe_subscription_id"] if row else ""
    if not subscription_id:
        return jsonify({"error": "サブスクリプション情報が見つかりませんでした。"}), 400

    stripe = get_stripe()
    try:
        stripe.Subscription.modify(subscription_id, cancel_at_period_end=False)
        return jsonify({"ok": True})
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.get("/api/billing/subscription")
def subscription_detail():
    """現在の契約が解約予約済みかどうかを、Stripe側の最新状態から返す(UI表示用)。"""
    code = session.get("access_code")
    if not code or not is_paid_session() or not stripe_enabled():
        return jsonify({"cancelAtPeriodEnd": False, "periodEnd": None})

    row = get_access_code(code)
    subscription_id = row["stripe_subscription_id"] if row else ""
    if not subscription_id:
        return jsonify({"cancelAtPeriodEnd": False, "periodEnd": None})

    stripe = get_stripe()
    try:
        subscription = stripe.Subscription.retrieve(subscription_id)
        period_end = _period_end_text(subscription)
        return jsonify({"cancelAtPeriodEnd": bool(subscription.cancel_at_period_end), "periodEnd": period_end})
    except Exception:  # noqa: BLE001
        return jsonify({"cancelAtPeriodEnd": False, "periodEnd": None})


@bp.post("/api/billing/webhook")
def webhook():
    stripe = get_stripe()
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = get_webhook_secret()

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            event = request.get_json(force=True)
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 400

    event_type = event["type"] if isinstance(event, dict) else event.type
    data_object = event["data"]["object"] if isinstance(event, dict) else event.data.object

    if event_type in ("customer.subscription.deleted",):
        set_access_code_status(data_object["id"], "cancelled")
    elif event_type == "customer.subscription.updated":
        new_status = data_object.get("status")
        if new_status in ("canceled", "unpaid", "past_due"):
            set_access_code_status(data_object["id"], "cancelled")
        elif new_status == "active":
            set_access_code_status(data_object["id"], "active")

    return jsonify({"received": True})


@bp.get("/api/billing/env-hint")
def env_hint():
    """開発時の確認用: 必要な環境変数が揃っているかだけを返す(値そのものは返さない)。"""
    return jsonify(
        {
            "STRIPE_SECRET_KEY": bool(os.environ.get("STRIPE_SECRET_KEY")),
            "STRIPE_PRICE_ID": bool(os.environ.get("STRIPE_PRICE_ID")),
            "STRIPE_WEBHOOK_SECRET": bool(os.environ.get("STRIPE_WEBHOOK_SECRET")),
        }
    )
