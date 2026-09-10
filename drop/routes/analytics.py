import os
import uuid

from flask import Blueprint, jsonify, request, session

from ..db import execute, query

bp = Blueprint("analytics", __name__, url_prefix="/api")


def _anon_id():
    """このブラウザを識別するための匿名ID(Cookieに保持、個人情報は含まない)。"""
    if "anon_id" not in session:
        session["anon_id"] = uuid.uuid4().hex[:12]
        session.modified = True
    return session["anon_id"]


@bp.post("/track")
def track():
    body = request.get_json(silent=True) or {}
    event_name = (body.get("event") or "pageview").strip()[:50] or "pageview"
    path = (body.get("path") or "").strip()[:200]
    referrer = (body.get("referrer") or "").strip()[:300]
    execute(
        "INSERT INTO events (event_name, path, referrer, session_id) VALUES (?, ?, ?, ?)",
        (event_name, path, referrer, _anon_id()),
    )
    return jsonify({"ok": True})


@bp.get("/admin/stats")
def admin_stats():
    key = request.args.get("key", "")
    expected = os.environ.get("ADMIN_KEY", "")
    if not expected or key != expected:
        return jsonify({"error": "unauthorized"}), 401

    totals = query(
        "SELECT event_name, COUNT(*) AS count, COUNT(DISTINCT session_id) AS unique_sessions "
        "FROM events GROUP BY event_name ORDER BY count DESC"
    )
    daily = query(
        "SELECT date(created_at) AS day, COUNT(*) AS count, COUNT(DISTINCT session_id) AS unique_sessions "
        "FROM events WHERE event_name = 'pageview' GROUP BY day ORDER BY day DESC LIMIT 30"
    )
    top_paths = query(
        "SELECT path, COUNT(*) AS count FROM events WHERE event_name = 'pageview' AND path != '' "
        "GROUP BY path ORDER BY count DESC LIMIT 30"
    )
    top_referrers = query(
        "SELECT referrer, COUNT(*) AS count FROM events "
        "WHERE event_name = 'pageview' AND referrer != '' "
        "GROUP BY referrer ORDER BY count DESC LIMIT 30"
    )
    recent = query("SELECT * FROM events ORDER BY id DESC LIMIT 100")

    return jsonify(
        {
            "totals": [dict(r) for r in totals],
            "daily": [dict(r) for r in daily],
            "topPaths": [dict(r) for r in top_paths],
            "topReferrers": [dict(r) for r in top_referrers],
            "recent": [dict(r) for r in recent],
        }
    )
