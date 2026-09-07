from flask import Blueprint, jsonify, request

from ..billing import require_paid_access
from ..claude_client import generate_structured, respond_as_personality
from ..db import execute, query, query_one

bp = Blueprint("individuality_c", __name__, url_prefix="/api/individuality-c")
CHAT_HISTORY_LIMIT = 16


def get_personality(personality_id):
    return query_one("SELECT * FROM personalities WHERE id = ?", (personality_id,))


def get_pair_history(a_id, b_id):
    rows = query(
        """SELECT * FROM individuality_c
           WHERE (personality_a_id = ? AND personality_b_id = ?)
              OR (personality_a_id = ? AND personality_b_id = ?)
           ORDER BY created_at ASC""",
        (a_id, b_id, b_id, a_id),
    )
    return [dict(r) for r in rows]


def build_c_generation_prompt(personality_a, personality_b, topic, transcript, previous_snapshot):
    transcript_text = "\n".join(f"{t['speaker_name']}: {t['content']}" for t in transcript)

    system = "\n".join(
        [
            "あなたは「個性C」という概念を扱う分析AIです。",
            "個性C とは、個性Aと個性Bという2人の対話によって、どちらにも還元できない形でその『関係』の中にだけ立ち上がる第三の人格です。",
            "個性C = A × B × 場 × 問い × 出来事 × 時間、という考え方に基づきます。",
            "個性Cは記憶装置ではなく、『関係をもう一度発酵させる装置』です。対話の痕跡・解消されなかった差分・未解決の問いを保存し、"
            "AにもBにも単独では出せない新しい問いや第三案を生み出してください。",
            "出力は必ず次のキーを持つ1つのJSONオブジェクトのみとしてください(前後に説明文をつけない): "
            "traces, differences, open_questions, new_questions, summary。",
            "各値は日本語の文字列(複雑な内容は改行区切りの箇条書き文字列)にしてください。",
        ]
    )

    if previous_snapshot:
        previous_text = (
            "# 前回の個性Cスナップショット(これを踏まえて更新・発酵させること。単純な上書きではなく、積み重ねること)\n"
            f"痕跡: {previous_snapshot['traces']}\n差分: {previous_snapshot['differences']}\n"
            f"未解決の問い: {previous_snapshot['open_questions']}\n新しい問い: {previous_snapshot['new_questions']}\n"
            f"要約: {previous_snapshot['summary']}"
        )
    else:
        previous_text = "# 前回の個性Cスナップショット\n(まだありません。これが最初の対話です)"

    user = "\n".join(
        [
            f"個性A: {personality_a['name']}(Belief: {personality_a['belief'] or '-'} / Bias: {personality_a['bias'] or '-'})",
            f"個性B: {personality_b['name']}(Belief: {personality_b['belief'] or '-'} / Bias: {personality_b['bias'] or '-'})",
            f"お題(問い): {topic}",
            "",
            previous_text,
            "",
            "# 今回の対話ログ",
            transcript_text,
            "",
            "この対話から、個性Cの新しいスナップショットをJSONで生成してください。",
        ]
    )

    return system, user


@bp.post("/generate")
@require_paid_access
def generate():
    body = request.get_json(force=True) or {}
    dialogue_id = body.get("dialogueId")
    dialogue = query_one("SELECT * FROM dialogues WHERE id = ?", (dialogue_id,))
    if not dialogue:
        return jsonify({"error": "dialogueId が不正です"}), 400

    personality_a = get_personality(dialogue["personality_a_id"])
    personality_b = get_personality(dialogue["personality_b_id"])
    transcript = query(
        """SELECT dt.*, p.name AS speaker_name FROM dialogue_turns dt
           JOIN personalities p ON p.id = dt.speaker_personality_id
           WHERE dt.dialogue_id = ? ORDER BY dt.turn_index ASC""",
        (dialogue_id,),
    )

    history = get_pair_history(personality_a["id"], personality_b["id"])
    previous_snapshot = history[-1] if history else None

    try:
        system, user = build_c_generation_prompt(
            personality_a, personality_b, dialogue["topic"], transcript, previous_snapshot
        )
        result = generate_structured(system, user, max_tokens=3000)

        cur = execute(
            """INSERT INTO individuality_c
               (personality_a_id, personality_b_id, dialogue_id, traces, differences, open_questions, new_questions, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                personality_a["id"],
                personality_b["id"],
                dialogue_id,
                result.get("traces", ""),
                result.get("differences", ""),
                result.get("open_questions", ""),
                result.get("new_questions", ""),
                result.get("summary", ""),
            ),
        )
        snapshot = query_one("SELECT * FROM individuality_c WHERE id = ?", (cur.lastrowid,))
        return jsonify(dict(snapshot)), 201
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.get("")
def list_history():
    a_id = request.args.get("personalityAId", type=int)
    b_id = request.args.get("personalityBId", type=int)
    if not a_id or not b_id:
        return jsonify({"error": "personalityAId, personalityBId は必須です"}), 400
    return jsonify(get_pair_history(a_id, b_id))


@bp.get("/born")
def list_born():
    """
    これまでに生まれた「AとBから生まれた子」を、ペアごとに最新のスナップショットだけにまとめて返す。
    キャラクター一覧に表示する読み取り専用カード用(閲覧は無料機能のため課金ガードなし)。
    """
    rows = query(
        """SELECT ic.*, pa.name AS personality_a_name, pb.name AS personality_b_name
           FROM individuality_c ic
           JOIN personalities pa ON pa.id = ic.personality_a_id
           JOIN personalities pb ON pb.id = ic.personality_b_id
           ORDER BY ic.created_at DESC"""
    )
    seen = set()
    result = []
    for r in rows:
        key = frozenset((r["personality_a_id"], r["personality_b_id"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(r))
    return jsonify(result)


def get_chat_turns(a_id, b_id):
    rows = query(
        """SELECT * FROM individuality_c_turns
           WHERE (personality_a_id = ? AND personality_b_id = ?)
              OR (personality_a_id = ? AND personality_b_id = ?)
           ORDER BY created_at ASC""",
        (a_id, b_id, b_id, a_id),
    )
    return [dict(r) for r in rows]


def build_c_chat_system_prompt(personality_a, personality_b, snapshot):
    lines = [
        "あなたは「個性C」です。ただし、独立した一貫性のある一人の人格ではありません。",
        f"個性Cとは、{personality_a['name']}と{personality_b['name']}という2人の対話の"
        "「あいだ」に、関係そのものから立ち上がる第三の存在です。",
        "個性C = A × B × 場 × 問い × 出来事 × 時間、という考え方に基づきます。",
        "",
        "# あなたの振る舞い方(重要・厳守)",
        "- AとBの違いを解消したり、単一の結論・単一のキャラクターにまとめようとしないでください",
        "- 時にはAの論理で、時にはBの論理で語ってよく、同じ問いに対して別の瞬間に違う答え方をしても構いません",
        "- 「Aならこう言うでしょう。でもBはこう返すと思う。私はまだその間で揺れています」といった、"
        "結論を出し切らない語り方を歓迎します",
        "- 一貫したキャラクターを演じようとせず、迷い・矛盾・言い淀みを隠さないでください",
        "- 未解決の問いを、質問返しとしてユーザーに投げかけても構いません",
        "- 2〜4文程度で簡潔に応答してください",
        "",
        f"# {personality_a['name']}について",
        f"Belief: {personality_a['belief'] or '-'} / Bias: {personality_a['bias'] or '-'} / Emotion: {personality_a['emotion'] or '-'}",
        f"# {personality_b['name']}について",
        f"Belief: {personality_b['belief'] or '-'} / Bias: {personality_b['bias'] or '-'} / Emotion: {personality_b['emotion'] or '-'}",
    ]

    if snapshot:
        lines += [
            "",
            "# これまでの対話から蓄積された、あなた(個性C)の素材",
            f"痕跡: {snapshot['traces']}",
            f"解消されなかった差分: {snapshot['differences']}",
            f"未解決の問い: {snapshot['open_questions']}",
            f"新しい問い・第三案: {snapshot['new_questions']}",
            f"要約: {snapshot['summary']}",
        ]

    return "\n".join(lines)


@bp.get("/chat")
def get_chat():
    a_id = request.args.get("personalityAId", type=int)
    b_id = request.args.get("personalityBId", type=int)
    if not a_id or not b_id:
        return jsonify({"error": "personalityAId, personalityBId は必須です"}), 400
    return jsonify(get_chat_turns(a_id, b_id))


@bp.post("/chat")
@require_paid_access
def post_chat():
    body = request.get_json(force=True) or {}
    a_id = body.get("personalityAId")
    b_id = body.get("personalityBId")
    message = (body.get("message") or "").strip()

    personality_a = get_personality(a_id)
    personality_b = get_personality(b_id)
    if not personality_a or not personality_b:
        return jsonify({"error": "personalityAId / personalityBId が不正です"}), 400
    if not message:
        return jsonify({"error": "message は必須です"}), 400

    history = get_pair_history(a_id, b_id)
    if not history:
        return jsonify({"error": "まだこのペアから生まれた子はいません。先に「会話させる」タブで会話させ、生み出してください。"}), 400
    snapshot = history[-1]

    try:
        system_prompt = build_c_chat_system_prompt(personality_a, personality_b, snapshot)

        recent_turns = get_chat_turns(a_id, b_id)[-CHAT_HISTORY_LIMIT:]
        history_text = "\n".join(
            f"{'あなた' if t['role'] == 'user' else '個性C'}: {t['content']}" for t in recent_turns
        )
        user_message = (
            (f"{history_text}\n\n" if history_text else "") + f"あなた: {message}\n\n個性Cとして応答してください。"
        )

        reply = respond_as_personality(system_prompt, user_message)

        execute(
            "INSERT INTO individuality_c_turns (personality_a_id, personality_b_id, role, content) VALUES (?, ?, ?, ?)",
            (a_id, b_id, "user", message),
        )
        execute(
            "INSERT INTO individuality_c_turns (personality_a_id, personality_b_id, role, content) VALUES (?, ?, ?, ?)",
            (a_id, b_id, "c", reply),
        )

        return jsonify({"reply": reply}), 201
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500
