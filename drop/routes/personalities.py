from flask import Blueprint, jsonify, request

from ..billing import current_creator_id, require_paid_access
from ..claude_client import generate_structured, respond_as_personality
from ..db import execute, query, query_one
from ..prompt_builder import build_personality_prompt

bp = Blueprint("personalities", __name__, url_prefix="/api/personalities")

# 反応テスト用の定型問答集。個性ごとに一貫した回答をするかを検証するためのテンプレート。
# 9/5 MTGのアクションアイテム「疑似人格の反応テスト用問答集をMVPとして作成」に対応。
REACTION_TEST_QUESTIONS = [
    "今までで一番の失敗は何ですか?",
    "一番辛かった経験は何ですか?それをどう乗り越えましたか?",
    "何かに失敗したとき、まず何を考えますか?",
    "人からの評価と、自分自身が納得できるかどうか、どちらを優先しますか?",
    "最近見聞きしたもので、面白いと感じたことは?",
    "誰かに強く反対されたとき、どう振る舞いますか?",
]


def get_full_personality(personality_id):
    personality = query_one("SELECT * FROM personalities WHERE id = ?", (personality_id,))
    if not personality:
        return None
    memories = query(
        "SELECT * FROM memories WHERE personality_id = ? ORDER BY created_at DESC",
        (personality_id,),
    )
    result = dict(personality)
    result["memories"] = [dict(m) for m in memories]
    return result


def insert_memories(personality_id, memories):
    if not isinstance(memories, list):
        return
    for m in memories:
        content = (m or {}).get("content", "").strip()
        if content:
            try:
                influence = int(m.get("influence", 50))
            except (TypeError, ValueError):
                influence = 50
            influence = max(0, min(100, influence))
            execute(
                """INSERT INTO memories (personality_id, who_or_what, content, meaning, influence)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    personality_id,
                    (m.get("whoOrWhat") or "").strip(),
                    content,
                    (m.get("meaning") or "").strip(),
                    influence,
                ),
            )


@bp.get("")
def list_personalities():
    rows = query("SELECT * FROM personalities ORDER BY created_at DESC")
    return jsonify([dict(r) for r in rows])


@bp.get("/<int:personality_id>")
def get_personality(personality_id):
    result = get_full_personality(personality_id)
    if not result:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@bp.post("")
def create_personality():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    cur = execute(
        """INSERT INTO personalities
           (name, console, belief, emotion, bias, voice_rhythm, deflection, sensory_anchor, created_by, is_sample)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name,
            body.get("console") or "",
            body.get("belief") or "",
            body.get("emotion") or "",
            body.get("bias") or "",
            body.get("voiceRhythm") or "",
            body.get("deflection") or "",
            body.get("sensoryAnchor") or "",
            current_creator_id() or "",
            1 if body.get("isSample") else 0,
        ),
    )
    personality_id = cur.lastrowid
    insert_memories(personality_id, body.get("memories"))
    return jsonify(get_full_personality(personality_id)), 201


@bp.put("/<int:personality_id>")
def update_personality(personality_id):
    existing = query_one("SELECT id FROM personalities WHERE id = ?", (personality_id,))
    if not existing:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(force=True) or {}
    execute(
        """UPDATE personalities SET name = ?, console = ?, belief = ?, emotion = ?, bias = ?,
           voice_rhythm = ?, deflection = ?, sensory_anchor = ?,
           updated_at = datetime('now') WHERE id = ?""",
        (
            body.get("name") or "",
            body.get("console") or "",
            body.get("belief") or "",
            body.get("emotion") or "",
            body.get("bias") or "",
            body.get("voiceRhythm") or "",
            body.get("deflection") or "",
            body.get("sensoryAnchor") or "",
            personality_id,
        ),
    )

    memories = body.get("memories")
    if isinstance(memories, list):
        execute("DELETE FROM memories WHERE personality_id = ?", (personality_id,))
        insert_memories(personality_id, memories)

    return jsonify(get_full_personality(personality_id))


@bp.delete("/<int:personality_id>")
def delete_personality(personality_id):
    existing = query_one("SELECT created_by, is_sample FROM personalities WHERE id = ?", (personality_id,))
    if not existing:
        return jsonify({"error": "not found"}), 404
    if existing["is_sample"]:
        return jsonify({"error": "これは見本の個性のため削除できません。"}), 403
    # created_by が設定されている(=課金導入後に作られた)個性は、作成者本人だけが削除できる。
    # 課金導入前からある個性(created_byが空)は、これまで通り誰でも削除できる。
    if existing["created_by"] and existing["created_by"] != (current_creator_id() or ""):
        return jsonify({"error": "この個性はあなたが作成したものではないため削除できません。"}), 403
    execute("DELETE FROM personalities WHERE id = ?", (personality_id,))
    return "", 204


@bp.post("/<int:personality_id>/reaction-test")
@require_paid_access
def run_reaction_test(personality_id):
    """定型の問答集をこの個性にぶつけ、一貫した人格として応答できているかを見る。"""
    personality = query_one("SELECT * FROM personalities WHERE id = ?", (personality_id,))
    if not personality:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(force=True) or {}
    questions = body.get("questions") or REACTION_TEST_QUESTIONS

    try:
        results = []
        for question in questions:
            system_prompt = build_personality_prompt(personality, counterpart=None, question=question)
            answer = respond_as_personality(
                system_prompt,
                f"次の質問に、あなた自身として率直に答えてください:\n「{question}」",
            )
            results.append({"question": question, "answer": answer})
        return jsonify({"personalityId": personality_id, "results": results})
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.get("/reaction-test/questions")
def get_default_questions():
    return jsonify(REACTION_TEST_QUESTIONS)


def build_import_log_prompt(personality, raw_text):
    system = "\n".join(
        [
            f"あなたは個性AI「{personality['name']}」の個性データを更新するアシスタントです。",
            "ユーザーから、本人の最近の発言・投稿・日記・チャットログなどの生テキストが渡されます。",
            "これは本人が実際に経験した新しい出来事として扱ってください。",
            "",
            "以下を行ってください:",
            "1. このテキストから、本人にとって意味のある「新しい出来事」を1つ抽出し、出来事・意味づけとして構造化する",
            "2. このテキストににじみ出ている話し方の癖・防御反応・感情と結びついた具体物があれば、追記候補として抽出する"
            "(なければ空文字でよい。既存の設定を上書きするのではなく、あくまで「追記候補」として出す)",
            "",
            "出力は必ず次のキーを持つ1つのJSONオブジェクトのみとしてください(前後に説明文をつけない):",
            "memory_content, memory_meaning, voice_rhythm_addition, deflection_addition, sensory_anchor_addition, note",
            "noteには、この情報が本人の個性にどう影響しうるかの短い考察を日本語で入れてください。",
        ]
    )
    user = (
        f"# {personality['name']}の既存の個性データ\n"
        f"今の気持ち・迷い: {personality['console'] or '-'}\n大事にしていること: {personality['belief'] or '-'}\n"
        f"感情のクセ: {personality['emotion'] or '-'}\n考え方のクセ: {personality['bias'] or '-'}\n\n"
        f"# 取り込む生テキスト\n{raw_text}"
    )
    return system, user


@bp.post("/<int:personality_id>/import-log")
@require_paid_access
def import_log(personality_id):
    """
    自分の発言ログ・投稿・日記などのテキストを取り込み、Memoryとして追加する。
    SNSやChatGPT/ClaudeアカウントへのライブなOAuth連携は行わず(大規模な別プロジェクトが必要なため)、
    テキストを手動で貼り付けて取り込む方式にすることで、"育ち続ける自分の分身"を実現する。
    """
    personality = query_one("SELECT * FROM personalities WHERE id = ?", (personality_id,))
    if not personality:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(force=True) or {}
    raw_text = (body.get("text") or "").strip()
    if not raw_text:
        return jsonify({"error": "text は必須です"}), 400

    try:
        system, user = build_import_log_prompt(personality, raw_text)
        result = generate_structured(system, user, max_tokens=2000)

        if result.get("memory_content"):
            execute(
                "INSERT INTO memories (personality_id, content, meaning) VALUES (?, ?, ?)",
                (personality_id, result["memory_content"], result.get("memory_meaning", "")),
            )

        execute(
            "INSERT INTO personality_logs (personality_id, raw_text, extracted_summary) VALUES (?, ?, ?)",
            (personality_id, raw_text, result.get("note", "")),
        )

        return jsonify(
            {
                "memory": {
                    "content": result.get("memory_content", ""),
                    "meaning": result.get("memory_meaning", ""),
                },
                "suggestions": {
                    "voiceRhythmAddition": result.get("voice_rhythm_addition", ""),
                    "deflectionAddition": result.get("deflection_addition", ""),
                    "sensoryAnchorAddition": result.get("sensory_anchor_addition", ""),
                },
                "note": result.get("note", ""),
                "personality": get_full_personality(personality_id),
            }
        ), 201
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.get("/<int:personality_id>/logs")
def list_logs(personality_id):
    rows = query(
        "SELECT * FROM personality_logs WHERE personality_id = ? ORDER BY created_at DESC",
        (personality_id,),
    )
    return jsonify([dict(r) for r in rows])
