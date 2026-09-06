from flask import Blueprint, jsonify, request

from ..billing import require_paid_access
from ..claude_client import respond_as_personality
from ..db import execute, query, query_one

bp = Blueprint("scenes", __name__, url_prefix="/api/scenes")


def get_personality(personality_id):
    return query_one("SELECT * FROM personalities WHERE id = ?", (personality_id,))


def get_relationship(personality_id, counterpart_id):
    return query_one(
        "SELECT * FROM relationship_context WHERE personality_id = ? AND counterpart_id = ?",
        (personality_id, counterpart_id),
    )


def describe_personality(p):
    lines = [
        f"# {p['name']}",
        f"Console: {p['console'] or '-'}",
        f"Belief: {p['belief'] or '-'}",
        f"Emotion: {p['emotion'] or '-'}",
        f"Bias: {p['bias'] or '-'}",
    ]
    if p["voice_rhythm"]:
        lines.append(f"Voice Rhythm(話し方の癖): {p['voice_rhythm']}")
    if p["deflection"]:
        lines.append(f"Deflection(本音とのズレ): {p['deflection']}")
    if p["sensory_anchor"]:
        lines.append(f"Sensory Anchor(感情と結びついた具体物): {p['sensory_anchor']}")

    memories = query(
        "SELECT content, meaning FROM memories WHERE personality_id = ? ORDER BY created_at DESC LIMIT 3",
        (p["id"],),
    )
    if memories:
        memory_text = "\n".join(f"  - {m['content']}(→ {m['meaning']})" for m in memories)
        lines.append(f"Memory:\n{memory_text}")
    return "\n".join(lines)


def build_scene_prompt(personality_a, personality_b, situation, raw_dialogue_text=None):
    rel_ab = get_relationship(personality_a["id"], personality_b["id"])
    rel_ba = get_relationship(personality_b["id"], personality_a["id"])

    system = "\n".join(
        [
            "あなたは、個性AIの設定をもとに、感情の機微を丁寧に描く短編小説の一場面を書く脚本家AIです。",
            "以下の人物設定・関係性をもとに、指定された状況で起きる一場面を、地の文と台詞を交えた短編小説形式で書いてください。",
            "",
            "# 執筆の絶対原則",
            "- 登場人物の感情を地の文で直接説明しないこと(「〜と感じた」「悲しかった」のような直接的な感情語を極力避ける)",
            "- 各人物のVoice Rhythm・Deflection・Sensory Anchorを、台詞だけでなく地の文の描写(仕草・視線・沈黙・周囲の物)にも積極的に使うこと",
            "- 沈黙・間・視線・仕草など、言葉にならないものを丁寧に描くこと",
            "- 「相手についての思い込み」がある場合、それに基づくすれ違いを、説明せずに行動と台詞の端々で滲ませること",
            "- 会話を完全に解決させず、場面の終わりに小さな変化(何かがわずかに動いた、という手触り)を置くこと",
            "- 三人称、簡潔で乾いた文体を基調とすること(説明過多を避け、余白を残す筆致)",
            "- 文字数は800〜1400字程度",
            "",
            "# 出力形式(厳守)",
            "1行目: 「タイトル: 」に続けて、この場面にふさわしい短いタイトル",
            "2行目: 空行",
            "3行目以降: 場面本文のみ(前置きや解説は一切書かない)",
        ]
    )

    parts = [describe_personality(personality_a), "", describe_personality(personality_b), ""]

    if rel_ab or rel_ba:
        parts.append("# 関係性")
        if rel_ab:
            parts.append(f"{personality_a['name']}→{personality_b['name']}: {rel_ab['notes'] or '(記録なし)'}")
            if rel_ab["misconception"]:
                parts.append(f"  {personality_a['name']}の思い込み: {rel_ab['misconception']}")
        if rel_ba:
            parts.append(f"{personality_b['name']}→{personality_a['name']}: {rel_ba['notes'] or '(記録なし)'}")
            if rel_ba["misconception"]:
                parts.append(f"  {personality_b['name']}の思い込み: {rel_ba['misconception']}")
        parts.append("")

    if raw_dialogue_text:
        parts.append("# 参考: 二人の実際のやり取り(この空気感を踏まえて場面を書く。逐語的になぞる必要はない)")
        parts.append(raw_dialogue_text)
        parts.append("")

    parts.append(f"# 今回の場面の状況\n{situation}")

    return system, "\n".join(parts)


def parse_scene_output(text):
    lines = text.strip().split("\n")
    title = ""
    body_start = 0
    if lines and lines[0].startswith("タイトル:"):
        title = lines[0].replace("タイトル:", "", 1).strip()
        body_start = 1
        while body_start < len(lines) and lines[body_start].strip() == "":
            body_start += 1
    content = "\n".join(lines[body_start:]).strip()
    return title or "(無題)", content or text.strip()


@bp.post("/generate")
@require_paid_access
def generate_scene():
    body = request.get_json(force=True) or {}
    personality_a = get_personality(body.get("personalityAId"))
    personality_b = get_personality(body.get("personalityBId"))
    situation = (body.get("situation") or "").strip()
    dialogue_id = body.get("dialogueId")

    if not personality_a or not personality_b:
        return jsonify({"error": "personalityAId / personalityBId が不正です"}), 400
    if not situation:
        return jsonify({"error": "situation(場面の状況)は必須です"}), 400

    raw_dialogue_text = None
    if dialogue_id:
        turns = query(
            """SELECT dt.*, p.name AS speaker_name FROM dialogue_turns dt
               JOIN personalities p ON p.id = dt.speaker_personality_id
               WHERE dt.dialogue_id = ? ORDER BY dt.turn_index ASC""",
            (dialogue_id,),
        )
        if turns:
            raw_dialogue_text = "\n".join(f"{t['speaker_name']}: {t['content']}" for t in turns)

    try:
        system, user = build_scene_prompt(personality_a, personality_b, situation, raw_dialogue_text)
        text = respond_as_personality(system, user, max_tokens=2200)
        title, content = parse_scene_output(text)

        cur = execute(
            """INSERT INTO scenes (personality_a_id, personality_b_id, situation, title, content)
               VALUES (?, ?, ?, ?, ?)""",
            (personality_a["id"], personality_b["id"], situation, title, content),
        )
        scene = query_one("SELECT * FROM scenes WHERE id = ?", (cur.lastrowid,))
        return jsonify(dict(scene)), 201
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.get("")
def list_scenes():
    a_id = request.args.get("personalityAId", type=int)
    b_id = request.args.get("personalityBId", type=int)
    if a_id and b_id:
        rows = query(
            """SELECT s.*, pa.name AS personality_a_name, pb.name AS personality_b_name FROM scenes s
               JOIN personalities pa ON pa.id = s.personality_a_id
               JOIN personalities pb ON pb.id = s.personality_b_id
               WHERE (s.personality_a_id = ? AND s.personality_b_id = ?)
                  OR (s.personality_a_id = ? AND s.personality_b_id = ?)
               ORDER BY s.created_at DESC""",
            (a_id, b_id, b_id, a_id),
        )
    else:
        rows = query(
            """SELECT s.*, pa.name AS personality_a_name, pb.name AS personality_b_name FROM scenes s
               JOIN personalities pa ON pa.id = s.personality_a_id
               JOIN personalities pb ON pb.id = s.personality_b_id
               ORDER BY s.created_at DESC"""
        )
    return jsonify([dict(r) for r in rows])
