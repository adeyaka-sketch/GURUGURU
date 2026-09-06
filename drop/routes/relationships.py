from flask import Blueprint, jsonify, request

from ..db import execute, query, query_one

bp = Blueprint("relationships", __name__, url_prefix="/api/relationships")


@bp.get("/<int:personality_id>")
def list_relationships(personality_id):
    """指定した個性を中心とした縁の地図データ(関係一覧)を返す。"""
    rows = query(
        """SELECT rc.*, p.name AS counterpart_name FROM relationship_context rc
           JOIN personalities p ON p.id = rc.counterpart_id
           WHERE rc.personality_id = ? ORDER BY rc.updated_at DESC""",
        (personality_id,),
    )
    return jsonify([dict(r) for r in rows])


@bp.get("/pair/<int:a_id>/<int:b_id>")
def get_pair(a_id, b_id):
    """A→B、B→Aそれぞれの視点の関係(非対称)をまとめて返す。"""
    a_to_b = query_one(
        "SELECT * FROM relationship_context WHERE personality_id = ? AND counterpart_id = ?", (a_id, b_id)
    )
    b_to_a = query_one(
        "SELECT * FROM relationship_context WHERE personality_id = ? AND counterpart_id = ?", (b_id, a_id)
    )
    memories_a = query(
        """SELECT * FROM subjective_memories WHERE personality_id = ? AND counterpart_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (a_id, b_id),
    )
    memories_b = query(
        """SELECT * FROM subjective_memories WHERE personality_id = ? AND counterpart_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (b_id, a_id),
    )
    return jsonify(
        {
            "aToB": dict(a_to_b) if a_to_b else None,
            "bToA": dict(b_to_a) if b_to_a else None,
            "memoriesA": [dict(m) for m in memories_a],
            "memoriesB": [dict(m) for m in memories_b],
        }
    )


@bp.put("/pair/<int:a_id>/<int:b_id>/label")
def set_relation_label(a_id, b_id):
    """縁の地図に表示する関係ラベル(例: 親子、元婚約者)を手動で設定する。両方向に同じラベルを付ける。"""
    body = request.get_json(force=True) or {}
    label = (body.get("label") or "").strip()

    for pid, cid in [(a_id, b_id), (b_id, a_id)]:
        existing = query_one(
            "SELECT id FROM relationship_context WHERE personality_id = ? AND counterpart_id = ?", (pid, cid)
        )
        if existing:
            execute(
                "UPDATE relationship_context SET relation_label = ? WHERE personality_id = ? AND counterpart_id = ?",
                (label, pid, cid),
            )
        else:
            execute(
                "INSERT INTO relationship_context (personality_id, counterpart_id, relation_label) VALUES (?, ?, ?)",
                (pid, cid, label),
            )
    return jsonify({"ok": True, "label": label})


@bp.put("/<int:personality_id>/<int:counterpart_id>/misconception")
def set_misconception(personality_id, counterpart_id):
    """
    personality_id視点で、counterpart_idについて持っている「本人も気づいていない思い込み」を設定する。
    A→BとB→Aは別物なので、片方向のみ更新する(対称なlabelとは異なる)。
    """
    body = request.get_json(force=True) or {}
    misconception = (body.get("misconception") or "").strip()

    existing = query_one(
        "SELECT id FROM relationship_context WHERE personality_id = ? AND counterpart_id = ?",
        (personality_id, counterpart_id),
    )
    if existing:
        execute(
            "UPDATE relationship_context SET misconception = ? WHERE personality_id = ? AND counterpart_id = ?",
            (misconception, personality_id, counterpart_id),
        )
    else:
        execute(
            "INSERT INTO relationship_context (personality_id, counterpart_id, misconception) VALUES (?, ?, ?)",
            (personality_id, counterpart_id, misconception),
        )
    return jsonify({"ok": True, "misconception": misconception})
