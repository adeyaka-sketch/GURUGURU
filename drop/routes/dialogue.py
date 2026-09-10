from datetime import date

from flask import Blueprint, jsonify, request

from ..billing import current_creator_id, require_paid_access
from ..claude_client import respond_with_reflection
from ..db import execute, query, query_one
from ..prompt_builder import build_personality_prompt
from .personalities import is_personality_visible

bp = Blueprint("dialogue", __name__, url_prefix="/api/dialogue")
MAX_TURNS = 8


def clamp(value, lo, hi):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    return max(lo, min(hi, value))


def get_personality(personality_id):
    return query_one("SELECT * FROM personalities WHERE id = ?", (personality_id,))


def ensure_relationship(personality_id, counterpart_id):
    existing = query_one(
        "SELECT * FROM relationship_context WHERE personality_id = ? AND counterpart_id = ?",
        (personality_id, counterpart_id),
    )
    if existing:
        return existing
    execute(
        "INSERT INTO relationship_context (personality_id, counterpart_id) VALUES (?, ?)",
        (personality_id, counterpart_id),
    )
    return query_one(
        "SELECT * FROM relationship_context WHERE personality_id = ? AND counterpart_id = ?",
        (personality_id, counterpart_id),
    )


def append_relationship_note(personality_id, counterpart_id, addition):
    rel = ensure_relationship(personality_id, counterpart_id)
    updated = f"{rel['notes']}\n- {addition}".strip() if rel["notes"] else f"- {addition}"
    execute(
        "UPDATE relationship_context SET notes = ?, updated_at = datetime('now') WHERE personality_id = ? AND counterpart_id = ?",
        (updated, personality_id, counterpart_id),
    )


def apply_relationship_deltas(personality_id, counterpart_id, reflection):
    rel = ensure_relationship(personality_id, counterpart_id)
    trust = clamp(rel["trust"] + (reflection.get("trust_delta") or 0), 0, 100)
    distance = clamp(rel["distance"] - (reflection.get("distance_delta") or 0), 0, 100)
    tension = clamp(rel["tension"] + (reflection.get("tension_delta") or 0), 0, 100)
    influence = clamp(rel["influence"] + (reflection.get("influence_delta") or 0), 0, 100)
    execute(
        """UPDATE relationship_context SET trust = ?, distance = ?, tension = ?, influence = ?,
           updated_at = datetime('now') WHERE personality_id = ? AND counterpart_id = ?""",
        (trust, distance, tension, influence, personality_id, counterpart_id),
    )


@bp.post("/start")
@require_paid_access
def start_dialogue():
    body = request.get_json(force=True) or {}
    personality_a = get_personality(body.get("personalityAId"))
    personality_b = get_personality(body.get("personalityBId"))
    topic = (body.get("topic") or "").strip()
    turn_count = min(max(int(body.get("turns") or 4), 1), MAX_TURNS)

    if not personality_a or not personality_b:
        return jsonify({"error": "personalityAId / personalityBId が不正です"}), 400
    requester_id = current_creator_id() or ""
    if not is_personality_visible(personality_a, requester_id) or not is_personality_visible(personality_b, requester_id):
        return jsonify({"error": "personalityAId / personalityBId が不正です"}), 400
    if not topic:
        return jsonify({"error": "問い(topic)は必須です"}), 400

    try:
        cur = execute(
            "INSERT INTO dialogues (personality_a_id, personality_b_id, topic) VALUES (?, ?, ?)",
            (personality_a["id"], personality_b["id"], topic),
        )
        dialogue_id = cur.lastrowid

        transcript = []
        last_message = topic
        speaker, listener = personality_a, personality_b

        for i in range(turn_count * 2):
            system_prompt = build_personality_prompt(speaker, counterpart=listener, question=last_message)
            if i == 0:
                user_message = (
                    f"対話のお題・問い: 「{last_message}」\n"
                    "このお題について、あなた自身の考えを述べてください。"
                )
            else:
                user_message = (
                    f"相手({listener['name']})が直前にこう言いました:\n「{last_message}」\n\n"
                    f"これに対して、あなた({speaker['name']})として応答してください。"
                )

            reflection = respond_with_reflection(system_prompt, user_message)
            content = reflection.get("reply", "").strip()

            execute(
                "INSERT INTO dialogue_turns (dialogue_id, speaker_personality_id, turn_index, content) VALUES (?, ?, ?, ?)",
                (dialogue_id, speaker["id"], i, content),
            )

            execute(
                """INSERT INTO subjective_memories
                   (personality_id, counterpart_id, dialogue_id, turn_index, content, emotion, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    speaker["id"],
                    listener["id"],
                    dialogue_id,
                    i,
                    reflection.get("memory", ""),
                    reflection.get("emotion", ""),
                    clamp(reflection.get("confidence"), 0, 100),
                ),
            )
            apply_relationship_deltas(speaker["id"], listener["id"], reflection)

            transcript.append(
                {
                    "speakerId": speaker["id"],
                    "speakerName": speaker["name"],
                    "turnIndex": i,
                    "content": content,
                    "emotion": reflection.get("emotion", ""),
                    "confidence": clamp(reflection.get("confidence"), 0, 100),
                }
            )

            last_message = content
            speaker, listener = listener, speaker

        today = date.today().isoformat()
        append_relationship_note(personality_a["id"], personality_b["id"], f"「{topic}」というお題で対話した({today})")
        append_relationship_note(personality_b["id"], personality_a["id"], f"「{topic}」というお題で対話した({today})")

        return jsonify({"dialogueId": dialogue_id, "topic": topic, "transcript": transcript}), 201
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.get("/<int:dialogue_id>")
def get_dialogue(dialogue_id):
    dialogue = query_one("SELECT * FROM dialogues WHERE id = ?", (dialogue_id,))
    if not dialogue:
        return jsonify({"error": "not found"}), 404
    turns = query(
        """SELECT dt.*, p.name AS speaker_name FROM dialogue_turns dt
           JOIN personalities p ON p.id = dt.speaker_personality_id
           WHERE dt.dialogue_id = ? ORDER BY dt.turn_index ASC""",
        (dialogue_id,),
    )
    result = dict(dialogue)
    result["turns"] = [dict(t) for t in turns]
    return jsonify(result)
