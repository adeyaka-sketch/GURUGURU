from flask import Blueprint, jsonify, request

from ..billing import require_paid_access
from ..claude_client import generate_structured
from ..db import execute, query, query_one

bp = Blueprint("self_discovery", __name__, url_prefix="/api/personalities")

MEMORY_LIMIT = 30


def get_personality(personality_id):
    return query_one("SELECT * FROM personalities WHERE id = ?", (personality_id,))


def build_reflection_prompt(personality, memories, relationships):
    memory_text = "\n".join(
        f"- (相手: {m['counterpart_name']} / 感情: {m['emotion']}・確信度{m['confidence']}%) {m['content']}"
        for m in memories
    )
    relationship_text = "\n".join(
        f"- {r['counterpart_name']}: 信頼{r['trust']}/距離{r['distance']}/緊張{r['tension']}/影響{r['influence']}"
        for r in relationships
    ) or "(まだ関係データがありません)"

    system = "\n".join(
        [
            "あなたは「気づきを促す」内省アシスタントです。",
            "ある人物が、これまで複数の相手との対話で見せてきた、実際の感情・行動パターンの記録を渡します。",
            "本人が今持っている自己認識(Console/Belief/Bias)と、複数の関係を横断した実際のパターンを比較し、"
            "本人がまだ言葉にできていない「気づき」を見つけてください。",
            "これは診断ではなく、本人の中にすでにあるが、まだ意識化されていないものを言語化する作業です。",
            "出力は必ず次のキーを持つ1つのJSONオブジェクトのみとしてください(前後に説明文をつけない):",
            "pattern_observed(複数の関係を横断して繰り返し見られる行動・感情パターン), "
            "gap(自己認識と実際のパターンのあいだのズレ), "
            "insight(本人の一人称視点で、初めて言葉にするような気づきの一文〜数文。断定しすぎず、まだ戸惑いを含んでよい), "
            "console_update(この気づきを踏まえた、今の気分・迷い・判断の状態。一人称視点の自然な文章で、Console欄をそのまま置き換えられる形式), "
            "belief_suggestion(信念(Belief)をもし更新するとしたら、という提案。強制ではない), "
            "bias_suggestion(偏り(Bias)の捉え方を更新するとしたら、という提案)",
        ]
    )

    user = "\n".join(
        [
            f"# {personality['name']}が今持っている自己認識",
            f"Console: {personality['console'] or '-'}",
            f"Belief: {personality['belief'] or '-'}",
            f"Emotion: {personality['emotion'] or '-'}",
            f"Bias: {personality['bias'] or '-'}",
            "",
            "# 複数の関係にまたがる、実際の主観的記憶(感情の記録)",
            memory_text,
            "",
            "# 相手ごとの関係スコア(このパターンも参考にしてよい)",
            relationship_text,
        ]
    )
    return system, user


@bp.get("/<int:personality_id>/self-discoveries")
def list_self_discoveries(personality_id):
    rows = query(
        "SELECT * FROM self_discoveries WHERE personality_id = ? ORDER BY created_at ASC",
        (personality_id,),
    )
    return jsonify([dict(r) for r in rows])


@bp.post("/<int:personality_id>/reflect")
@require_paid_access
def reflect(personality_id):
    """
    複数の相手との対話で蓄積された主観的記憶を横断的に振り返り、
    「自分が思っていた自分」と「実際の行動パターン」のズレ(気づき)を言語化する。
    Consoleは自動更新(今この瞬間の状態という性質上)。Belief/Biasは提案のみで、
    アイデンティティの根幹を勝手に上書きしない。
    """
    personality = get_personality(personality_id)
    if not personality:
        return jsonify({"error": "not found"}), 404

    memories = query(
        """SELECT sm.*, p.name AS counterpart_name FROM subjective_memories sm
           JOIN personalities p ON p.id = sm.counterpart_id
           WHERE sm.personality_id = ? ORDER BY sm.created_at DESC LIMIT ?""",
        (personality_id, MEMORY_LIMIT),
    )
    if not memories:
        return jsonify({"error": "まだ対話履歴が十分ではありません。対話を重ねてから試してください。"}), 400

    relationships = query(
        """SELECT rc.*, p.name AS counterpart_name FROM relationship_context rc
           JOIN personalities p ON p.id = rc.counterpart_id
           WHERE rc.personality_id = ?""",
        (personality_id,),
    )

    try:
        system, user = build_reflection_prompt(personality, memories, relationships)
        result = generate_structured(system, user, max_tokens=3000)

        previous_console = personality["console"]
        new_console = result.get("console_update") or previous_console

        execute(
            "UPDATE personalities SET console = ?, updated_at = datetime('now') WHERE id = ?",
            (new_console, personality_id),
        )

        cur = execute(
            """INSERT INTO self_discoveries
               (personality_id, pattern_observed, gap, insight, previous_console, new_console,
                belief_suggestion, bias_suggestion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                personality_id,
                result.get("pattern_observed", ""),
                result.get("gap", ""),
                result.get("insight", ""),
                previous_console,
                new_console,
                result.get("belief_suggestion", ""),
                result.get("bias_suggestion", ""),
            ),
        )
        discovery = query_one("SELECT * FROM self_discoveries WHERE id = ?", (cur.lastrowid,))
        return jsonify(dict(discovery)), 201
    except Exception as err:  # noqa: BLE001
        return jsonify({"error": str(err)}), 500


@bp.post("/<int:personality_id>/self-discoveries/<int:discovery_id>/apply")
def apply_self_discovery(personality_id, discovery_id):
    """Belief/Biasの提案を、ユーザーの確認のもとで実際に反映する。"""
    discovery = query_one(
        "SELECT * FROM self_discoveries WHERE id = ? AND personality_id = ?", (discovery_id, personality_id)
    )
    if not discovery:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(force=True) or {}
    apply_belief = bool(body.get("applyBelief"))
    apply_bias = bool(body.get("applyBias"))

    if apply_belief and discovery["belief_suggestion"]:
        execute(
            "UPDATE personalities SET belief = ?, updated_at = datetime('now') WHERE id = ?",
            (discovery["belief_suggestion"], personality_id),
        )
        execute("UPDATE self_discoveries SET belief_applied = 1 WHERE id = ?", (discovery_id,))

    if apply_bias and discovery["bias_suggestion"]:
        execute(
            "UPDATE personalities SET bias = ?, updated_at = datetime('now') WHERE id = ?",
            (discovery["bias_suggestion"], personality_id),
        )
        execute("UPDATE self_discoveries SET bias_applied = 1 WHERE id = ?", (discovery_id,))

    updated_personality = get_personality(personality_id)
    updated_discovery = query_one("SELECT * FROM self_discoveries WHERE id = ?", (discovery_id,))
    return jsonify({"personality": dict(updated_personality), "discovery": dict(updated_discovery)})
