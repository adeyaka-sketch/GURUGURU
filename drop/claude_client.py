import json
import os
import re

from anthropic import Anthropic

_client = None
MODEL = os.environ.get("MODEL", "claude-sonnet-5")


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def respond_as_personality(system_prompt, user_message, max_tokens=600):
    res = _get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return "\n".join(block.text for block in res.content if block.type == "text").strip()


def generate_structured(system_prompt, user_message, max_tokens=1500):
    res = _get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    text = "\n".join(block.text for block in res.content if block.type == "text").strip()

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"構造化JSONの抽出に失敗しました: {text[:200]}")
    return json.loads(match.group(0))


REFLECTION_INSTRUCTION = """

# 出力形式(重要)
あなたの発言そのものだけでなく、その発言の裏側にある「あなた自身の主観的な記憶と感情」も同時に出力してください。
これは「対話ログの記録(メモリ)」ではなく「その瞬間どう感じたか(記憶)」です。同じ会話でも相手とは違う記憶になって構いません。

出力は必ず次のキーを持つ1つのJSONオブジェクトのみとしてください(前後に説明文をつけない):
- reply: 実際の発言内容(文字列)
- emotion: 今の気持ちを表す一言(例: trust, sadness, mixed, tension, relief, anger, joy など日本語でも可)
- confidence: その感情の強さ(0〜100の整数)
- memory: この瞬間をどう記憶するか、本人の一人称視点での短い一文
- trust_delta: 相手への信頼が今回の発言でどう変化したか(-15〜15の整数)
- distance_delta: 相手との心理的距離が縮まった(負)か離れた(正)か(-15〜15の整数)
- tension_delta: 緊張・警戒が増えた(正)か和らいだ(負)か(-15〜15の整数)
- influence_delta: 相手から今回受けた影響の大きさ(0〜15の整数)
"""


def respond_with_reflection(system_prompt, user_message):
    """発言(reply)と同時に、話者本人の主観的な記憶・感情・関係性スコアの変化を構造化生成する。"""
    return generate_structured(system_prompt + REFLECTION_INSTRUCTION, user_message, max_tokens=800)
