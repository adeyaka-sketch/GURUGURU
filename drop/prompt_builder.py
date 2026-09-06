import re

from .db import query, query_one


def get_memories(personality_id):
    return query(
        "SELECT content, meaning FROM memories WHERE personality_id = ? ORDER BY created_at DESC",
        (personality_id,),
    )


def get_relationship(personality_id, counterpart_id):
    return query_one(
        "SELECT * FROM relationship_context WHERE personality_id = ? AND counterpart_id = ?",
        (personality_id, counterpart_id),
    )


def select_relevant_memories(memories, question, limit=5):
    """question文と単純なキーワード一致で関連しそうなMemoryを上位に並べる(v1簡易版)"""
    if not question:
        return memories[:limit]
    keywords = [w for w in re.split(r"[\s、。,.!?！？]+", question) if len(w) >= 2]

    def score(m):
        text = f"{m['content']} {m['meaning']}"
        return sum(1 for kw in keywords if kw in text)

    scored = sorted(memories, key=score, reverse=True)
    return scored[:limit]


def build_personality_prompt(personality, counterpart=None, question=None):
    """
    個性データ + 状況(相手・問い)から、その場に必要なプロンプトを動的生成する。
    PDFのフロー: 相手・状況・問い → 個性データを選択 → 動的プロンプト生成

    「本音をそのまま言わせる」のではなく「本音と言動のあいだにズレを作る」ことを狙う。
    実在の人間が"感情の説明装置"ではなく生きて見えるのは、内面をそのまま言葉にしないから、
    という前提(生方美久脚本の分析)に基づく設計。
    """
    memories = get_memories(personality["id"])
    relevant = select_relevant_memories(memories, question)
    relationship = get_relationship(personality["id"], counterpart["id"]) if counterpart else None

    lines = []
    lines.append(f"あなたは個性AI「{personality['name']}」本人として応答します。")
    lines.append(
        "以下は、この人物の「本当の中身」です。これは、そのまま言葉にしてよい情報ではありません。"
        "現実の人間は、自分の感情や判断基準を正確に実況したりしません。むしろ隠す・照れる・誤魔化す・"
        "話題を逸らす生き物です。あなたの仕事は、この中身を「漏らす」ことであって、「説明する」ことではありません。"
    )
    lines.append(f"# Console(今、どう感じ、迷い、判断しているか)\n{personality['console'] or '(未設定)'}")
    lines.append(f"# Belief(何を信じ、何を守ろうとするか)\n{personality['belief'] or '(未設定)'}")
    lines.append(f"# Emotion(感情が判断をどう変えるか)\n{personality['emotion'] or '(未設定)'}")
    lines.append(f"# Bias(本人固有の偏り・判断のクセ)\n{personality['bias'] or '(未設定)'}")

    if personality["voice_rhythm"]:
        lines.append(
            f"# Voice Rhythm(話し方の癖・間・口癖 —— 内容以上に、これが「その人だとわかる」手がかりです)\n"
            f"{personality['voice_rhythm']}"
        )

    if personality["deflection"]:
        lines.append(
            "# Deflection(本音とのズレ・防御反応 —— 最重要)\n"
            f"{personality['deflection']}\n"
            "強く感情が動いた瞬間ほど、感情をそのまま言葉にせず、この防御反応を優先してください。"
            "「本当は〜と思っている」と地の文で説明するのではなく、行動・話題転換・沈黙・軽口として滲ませてください。"
        )

    if personality["sensory_anchor"]:
        lines.append(
            "# Sensory Anchor(この人固有の、感情と結びついた具体物・場所・天気・感覚)\n"
            f"{personality['sensory_anchor']}\n"
            "関連する場面では、感情を名指しする代わりに、これらの具体物にさりげなく触れることで感情を示唆してください。"
            "意味を説明しないでください。"
        )

    if relevant:
        memory_text = "\n".join(
            f"- 経験: {m['content']} / 意味づけ: {m['meaning'] or '(なし)'}" for m in relevant
        )
        lines.append(
            f"# Memory(関連する経験と意味づけ —— ただしこれは「あなたの解釈」であり、相手と共有された事実ではありません)\n{memory_text}"
        )

    if counterpart:
        lines.append(f"# Relationship Context(相手「{counterpart['name']}」との関係)")
        if relationship:
            lines.append(
                f"信頼度{relationship['trust']}/100・心理的距離{relationship['distance']}/100"
                f"(小さいほど近い)・緊張度{relationship['tension']}/100"
                f"(これはあなた視点での主観的な数値です。相手も同じ数値とは限りません)"
            )
            lines.append(relationship["notes"] or "(まだ具体的な出来事の記録はありません)")
            if relationship["misconception"]:
                lines.append(
                    f"# 相手についての、あなた自身も気づいていない思い込み\n{relationship['misconception']}\n"
                    "これは間違っている可能性がありますが、あなた自身はそれに気づいていません。"
                    "この思い込みを前提として自然に振る舞い、ユーザーや相手から指摘されても、"
                    "すぐには手放さないでください。"
                )
        else:
            lines.append("(まだこの相手との対話履歴はありません)")

    lines.append("# 応答の絶対ルール")
    lines.append("- 自分の感情や判断基準を、地の文のように直接説明・命名しないこと(「私は〜と感じている」を禁止)")
    lines.append("- Deflection・Sensory Anchorが設定されている場合は、感情が動く場面ほど積極的に使うこと")
    lines.append("- Voice Rhythmの文体・口癖・間の取り方を、内容以上に優先して一貫させること")
    lines.append("- 一般論や優等生的な回答を避け、この人物固有の判断基準・迷い・偏りを反映すること")
    lines.append("- 2〜4文程度で、実際の対話のように簡潔に応答すること")

    return "\n\n".join(lines)
