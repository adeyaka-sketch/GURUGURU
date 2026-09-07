const state = {
  personalities: [],
  bornChildren: [],
  selectedPersonalityId: null,
  lastDialogueId: null,
  cChatPair: null,
};

// ---------- タブ切り替え ----------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "dialogue" || btn.dataset.tab === "individuality-c") {
      fillPersonalitySelects();
    }
    if (btn.dataset.tab === "enishi-map") {
      fillMapCenterSelect();
    }
    if (btn.dataset.tab === "reaction-test") {
      fillReactionTestSelect();
    }
    if (btn.dataset.tab === "scene-studio") {
      fillPersonalitySelects();
      refreshSceneHistoryFromSelects();
    }
  });
});

function refreshSceneHistoryFromSelects() {
  const aId = document.getElementById("scene-personality-a").value;
  const bId = document.getElementById("scene-personality-b").value;
  if (aId && bId) loadSceneHistory(aId, bId);
}

["scene-personality-a", "scene-personality-b"].forEach((id) => {
  document.getElementById(id).addEventListener("change", refreshSceneHistoryFromSelects);
});

// ---------- API helpers ----------
async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 402) {
    const err = await res.json().catch(() => ({}));
    showPaywall("plan");
    throw new Error(err.error || "この機能は有料プランが必要です。");
  }
  if (res.status === 429) {
    const err = await res.json().catch(() => ({}));
    showPaywall("usage");
    throw new Error(err.error || "今月の利用上限に達しました。");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || "リクエストに失敗しました");
  }
  if (res.status === 204) return null;
  return res.json();
}

// ---------- キャラクター ----------
async function loadPersonalities() {
  const [personalities, bornChildren] = await Promise.all([
    api("/personalities"),
    api("/individuality-c/born").catch(() => []),
  ]);
  state.personalities = personalities;
  state.bornChildren = bornChildren;
  renderPersonalityList();
  fillPersonalitySelects();
}

function renderPersonalityList() {
  const list = document.getElementById("personality-list");
  list.innerHTML = "";
  state.personalities.forEach((p) => {
    const li = document.createElement("li");
    li.textContent = p.name;
    li.dataset.id = p.id;
    if (p.id === state.selectedPersonalityId) li.classList.add("selected");
    li.addEventListener("click", () => selectPersonality(p.id));
    list.appendChild(li);
  });
  (state.bornChildren || []).forEach((c) => {
    const li = document.createElement("li");
    li.className = "born-child-item";
    li.innerHTML = `<span class="born-child-badge">生まれた子</span>${escapeHtml(c.personality_a_name)} と ${escapeHtml(c.personality_b_name)} から生まれた子`;
    li.addEventListener("click", () => openBornChild(c.personality_a_id, c.personality_b_id));
    list.appendChild(li);
  });
}

function openBornChild(aId, bId) {
  document.querySelector('.tab-btn[data-tab="individuality-c"]').click();
  document.getElementById("c-personality-a").value = aId;
  document.getElementById("c-personality-b").value = bId;
  document.getElementById("c-select-form").requestSubmit();
}

function fillPersonalitySelects() {
  const selects = [
    "d-personality-a",
    "d-personality-b",
    "c-personality-a",
    "c-personality-b",
    "map-center-select",
    "rt-personality",
    "scene-personality-a",
    "scene-personality-b",
  ];
  selects.forEach((id) => {
    const select = document.getElementById(id);
    const current = select.value;
    select.innerHTML = "";
    state.personalities.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      select.appendChild(opt);
    });
    if (current) select.value = current;
  });
}

async function selectPersonality(id) {
  state.selectedPersonalityId = id;
  renderPersonalityList();
  const p = await api(`/personalities/${id}`);
  document.getElementById("personality-form-title").textContent = `編集: ${p.name}`;
  document.getElementById("personality-id").value = p.id;
  document.getElementById("p-name").value = p.name;
  document.getElementById("p-console").value = p.console || "";
  document.getElementById("p-belief").value = p.belief || "";
  document.getElementById("p-emotion").value = p.emotion || "";
  document.getElementById("p-bias").value = p.bias || "";
  document.getElementById("p-voice-rhythm").value = p.voice_rhythm || "";
  document.getElementById("p-deflection").value = p.deflection || "";
  document.getElementById("p-sensory-anchor").value = p.sensory_anchor || "";
  renderMemoryRows(p.memories || []);
  document.getElementById("delete-personality-btn").style.display = "inline-block";
  document.getElementById("import-log-section").style.display = "block";
  document.getElementById("import-log-result").innerHTML = "";
  document.getElementById("reflect-section").style.display = "block";
  await loadSelfDiscoveries(id);
}

function resetPersonalityForm() {
  state.selectedPersonalityId = null;
  renderPersonalityList();
  document.getElementById("personality-form-title").textContent = "新しい個性";
  document.getElementById("personality-form").reset();
  document.getElementById("personality-id").value = "";
  renderMemoryRows([]);
  document.getElementById("delete-personality-btn").style.display = "none";
  document.getElementById("import-log-section").style.display = "none";
  document.getElementById("reflect-section").style.display = "none";
}

function renderMemoryRows(memories) {
  const container = document.getElementById("memory-list");
  container.innerHTML = "";
  memories
    .slice()
    .sort((a, b) => (b.influence ?? 50) - (a.influence ?? 50))
    .forEach((m) => addMemoryRow(m.who_or_what, m.content, m.meaning, m.influence));
  if (memories.length === 0) addMemoryRow();
}

function addMemoryRow(whoOrWhat = "", content = "", meaning = "", influence = 50) {
  const container = document.getElementById("memory-list");
  const row = document.createElement("div");
  row.className = "memory-row";
  row.innerHTML = `
    <input type="text" placeholder="誰・何との出会いか(例: 母、初めての職場、あの日の雨)" class="memory-who" value="${escapeHtml(whoOrWhat)}" />
    <input type="text" placeholder="どんな出来事だったか" class="memory-content" value="${escapeHtml(content)}" />
    <input type="text" placeholder="どう感じ、今にどう影響しているか" class="memory-meaning" value="${escapeHtml(meaning)}" />
    <div class="memory-influence-row">
      <label>影響度</label>
      <input type="range" min="0" max="100" class="memory-influence" value="${influence ?? 50}" />
      <span class="memory-influence-value">${influence ?? 50}</span>
    </div>
    <button type="button" class="secondary remove-memory">×</button>
  `;
  const slider = row.querySelector(".memory-influence");
  const valueLabel = row.querySelector(".memory-influence-value");
  slider.addEventListener("input", () => {
    valueLabel.textContent = slider.value;
  });
  row.querySelector(".remove-memory").addEventListener("click", () => row.remove());
  container.appendChild(row);
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

document.getElementById("new-personality-btn").addEventListener("click", resetPersonalityForm);
document.getElementById("add-memory-btn").addEventListener("click", () => addMemoryRow());

document.getElementById("personality-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = document.getElementById("personality-id").value;
  const memories = Array.from(document.querySelectorAll(".memory-row")).map((row) => ({
    whoOrWhat: row.querySelector(".memory-who").value,
    content: row.querySelector(".memory-content").value,
    meaning: row.querySelector(".memory-meaning").value,
    influence: Number(row.querySelector(".memory-influence").value),
  }));
  const payload = {
    name: document.getElementById("p-name").value,
    console: document.getElementById("p-console").value,
    belief: document.getElementById("p-belief").value,
    emotion: document.getElementById("p-emotion").value,
    bias: document.getElementById("p-bias").value,
    voiceRhythm: document.getElementById("p-voice-rhythm").value,
    deflection: document.getElementById("p-deflection").value,
    sensoryAnchor: document.getElementById("p-sensory-anchor").value,
    memories,
  };

  try {
    if (id) {
      await api(`/personalities/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      const created = await api("/personalities", { method: "POST", body: JSON.stringify(payload) });
      state.selectedPersonalityId = created.id;
    }
    await loadPersonalities();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("delete-personality-btn").addEventListener("click", async () => {
  const id = document.getElementById("personality-id").value;
  if (!id) return;
  if (!confirm("この個性を削除しますか?")) return;
  await api(`/personalities/${id}`, { method: "DELETE" });
  resetPersonalityForm();
  await loadPersonalities();
});

document.getElementById("import-log-btn").addEventListener("click", async () => {
  const id = document.getElementById("personality-id").value;
  const textEl = document.getElementById("import-log-text");
  const resultEl = document.getElementById("import-log-result");
  const text = textEl.value.trim();
  if (!id || !text) return;

  resultEl.innerHTML = '<p class="hint">取り込み中...</p>';
  try {
    const result = await api(`/personalities/${id}/import-log`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    textEl.value = "";
    const s = result.suggestions || {};
    resultEl.innerHTML = `
      <div class="suggestion-card">
        <div><strong>追加された出来事:</strong> ${escapeHtml(result.memory.content)}</div>
        <div class="hint">どう感じたか: ${escapeHtml(result.memory.meaning || "-")}</div>
        ${result.note ? `<div class="suggestion-label">考察</div><div>${escapeHtml(result.note)}</div>` : ""}
        ${s.voiceRhythmAddition ? `<div class="suggestion-label">話し方のクセ 追記候補</div><div>${escapeHtml(s.voiceRhythmAddition)}</div>` : ""}
        ${s.deflectionAddition ? `<div class="suggestion-label">本音を隠すときの様子 追記候補</div><div>${escapeHtml(s.deflectionAddition)}</div>` : ""}
        ${s.sensoryAnchorAddition ? `<div class="suggestion-label">思い出の品・匂い・場所 追記候補</div><div>${escapeHtml(s.sensoryAnchorAddition)}</div>` : ""}
        <p class="hint">追記候補は自動反映されません。良ければ上のフォームに手動でコピーして保存してください。</p>
      </div>
    `;
    if (result.personality) {
      renderMemoryRows(result.personality.memories || []);
    }
  } catch (err) {
    resultEl.innerHTML = "";
    alert(err.message);
  }
});

// ---------- 気づき(自己発見) ----------
async function loadSelfDiscoveries(id) {
  const list = await api(`/personalities/${id}/self-discoveries`);
  renderSelfDiscoveryTimeline(id, list);
}

function renderSelfDiscoveryTimeline(personalityId, list) {
  const timeline = document.getElementById("self-discovery-timeline");
  timeline.innerHTML = "";
  if (list.length === 0) {
    timeline.innerHTML = '<p class="hint">まだ気づきはありません。対話を重ねてから「対話をふりかえる」を押してください。</p>';
    return;
  }
  list.slice().reverse().forEach((d) => {
    const card = document.createElement("div");
    card.className = "c-card";
    card.innerHTML = `
      <div class="c-date">${d.created_at}</div>
      ${cField("繰り返し見られたパターン", d.pattern_observed)}
      ${cField("自己認識とのズレ", d.gap)}
      ${cField("気づき", d.insight)}
      ${cField("Console の変化", `${d.previous_console || "(未設定)"}\n\n↓\n\n${d.new_console || "(未設定)"}`)}
      ${d.belief_suggestion ? `
        <div class="c-field">
          <div class="c-field-label">Belief 提案 ${d.belief_applied ? "(反映済み)" : ""}</div>
          <div class="c-field-value">${escapeHtml(d.belief_suggestion)}</div>
          ${!d.belief_applied ? `<button type="button" class="secondary apply-belief-btn" data-id="${d.id}">この提案をBeliefに反映する</button>` : ""}
        </div>` : ""}
      ${d.bias_suggestion ? `
        <div class="c-field">
          <div class="c-field-label">Bias 提案 ${d.bias_applied ? "(反映済み)" : ""}</div>
          <div class="c-field-value">${escapeHtml(d.bias_suggestion)}</div>
          ${!d.bias_applied ? `<button type="button" class="secondary apply-bias-btn" data-id="${d.id}">この提案をBiasに反映する</button>` : ""}
        </div>` : ""}
    `;
    timeline.appendChild(card);
  });

  timeline.querySelectorAll(".apply-belief-btn").forEach((btn) => {
    btn.addEventListener("click", () => applySelfDiscovery(personalityId, btn.dataset.id, { applyBelief: true }));
  });
  timeline.querySelectorAll(".apply-bias-btn").forEach((btn) => {
    btn.addEventListener("click", () => applySelfDiscovery(personalityId, btn.dataset.id, { applyBias: true }));
  });
}

async function applySelfDiscovery(personalityId, discoveryId, body) {
  try {
    await api(`/personalities/${personalityId}/self-discoveries/${discoveryId}/apply`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    await selectPersonality(personalityId);
    await loadPersonalities();
  } catch (err) {
    alert(err.message);
  }
}

document.getElementById("reflect-btn").addEventListener("click", async () => {
  const id = document.getElementById("personality-id").value;
  const statusEl = document.getElementById("reflect-status");
  if (!id) return;

  statusEl.textContent = "対話をふりかえっています...";
  try {
    await api(`/personalities/${id}/reflect`, { method: "POST", body: JSON.stringify({}) });
    statusEl.textContent = "";
    await selectPersonality(id);
  } catch (err) {
    statusEl.textContent = "";
    alert(err.message);
  }
});

// ---------- 対話 ----------
document.getElementById("dialogue-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const personalityAId = document.getElementById("d-personality-a").value;
  const personalityBId = document.getElementById("d-personality-b").value;
  const topic = document.getElementById("d-topic").value;
  const turns = document.getElementById("d-turns").value;

  if (personalityAId === personalityBId) {
    alert("個性Aと個性Bは異なる個性を選んでください");
    return;
  }

  const statusEl = document.getElementById("dialogue-status");
  const transcriptEl = document.getElementById("dialogue-transcript");
  transcriptEl.innerHTML = "";
  statusEl.textContent = "対話を生成中...(Claude APIを呼び出しています)";
  document.getElementById("generate-c-btn").style.display = "none";

  try {
    const result = await api("/dialogue/start", {
      method: "POST",
      body: JSON.stringify({ personalityAId, personalityBId, topic, turns }),
    });
    state.lastDialogueId = result.dialogueId;
    renderTranscript(result.transcript, personalityAId);
    statusEl.textContent = `対話が完了しました(${result.transcript.length}ターン)`;
    document.getElementById("generate-c-btn").style.display = "inline-block";
  } catch (err) {
    statusEl.textContent = "";
    alert(err.message);
  }
});

function renderTranscript(transcript, personalityAId) {
  const transcriptEl = document.getElementById("dialogue-transcript");
  transcriptEl.innerHTML = "";
  transcript.forEach((turn) => {
    const bubble = document.createElement("div");
    const isA = String(turn.speakerId) === String(personalityAId);
    bubble.className = `bubble ${isA ? "speaker-a" : "speaker-b"}`;
    const emotionTag = turn.emotion
      ? `<span class="emotion-tag">${escapeHtml(turn.emotion)} ${turn.confidence ?? ""}%</span>`
      : "";
    bubble.innerHTML = `<div class="speaker-name">${escapeHtml(turn.speakerName)}${emotionTag}</div><div>${escapeHtml(turn.content)}</div>`;
    transcriptEl.appendChild(bubble);
  });
}

document.getElementById("generate-c-btn").addEventListener("click", async () => {
  if (!state.lastDialogueId) return;
  const btn = document.getElementById("generate-c-btn");
  btn.disabled = true;
  btn.textContent = "あたらしい子を生み出しています...";
  try {
    await api("/individuality-c/generate", {
      method: "POST",
      body: JSON.stringify({ dialogueId: state.lastDialogueId }),
    });
    alert("あたらしい子が生まれました。「生まれた子」タブで確認できます。");
    await loadPersonalities();
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "この対話から、あたらしい子を生み出す";
  }
});

// ---------- 生まれた子(個性C) ----------
document.getElementById("c-select-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const aId = document.getElementById("c-personality-a").value;
  const bId = document.getElementById("c-personality-b").value;
  const timeline = document.getElementById("c-timeline");
  timeline.innerHTML = "読み込み中...";

  try {
    const history = await api(`/individuality-c?personalityAId=${aId}&personalityBId=${bId}`);
    renderCTimeline(history);

    const chatSection = document.getElementById("c-chat-section");
    if (history.length > 0) {
      state.cChatPair = { aId, bId };
      chatSection.style.display = "block";
      const turns = await api(`/individuality-c/chat?personalityAId=${aId}&personalityBId=${bId}`);
      renderCChatLog(turns);
    } else {
      state.cChatPair = null;
      chatSection.style.display = "none";
    }
  } catch (err) {
    timeline.innerHTML = "";
    alert(err.message);
  }
});

function renderCChatLog(turns) {
  const log = document.getElementById("c-chat-log");
  log.innerHTML = "";
  if (turns.length === 0) {
    log.innerHTML = '<p class="hint">まだ会話がありません。下から話しかけてみてください。</p>';
    return;
  }
  turns.forEach((t) => {
    const bubble = document.createElement("div");
    bubble.className = `c-chat-bubble role-${t.role}`;
    bubble.innerHTML = `<div class="c-chat-role">${t.role === "user" ? "あなた" : "生まれた子"}</div><div>${escapeHtml(t.content)}</div>`;
    log.appendChild(bubble);
  });
  log.scrollTop = log.scrollHeight;
}

document.getElementById("c-chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.cChatPair) return;
  const input = document.getElementById("c-chat-input");
  const message = input.value.trim();
  if (!message) return;

  const log = document.getElementById("c-chat-log");
  const userBubble = document.createElement("div");
  userBubble.className = "c-chat-bubble role-user";
  userBubble.innerHTML = `<div class="c-chat-role">あなた</div><div>${escapeHtml(message)}</div>`;
  log.appendChild(userBubble);
  log.scrollTop = log.scrollHeight;
  input.value = "";

  try {
    const { aId, bId } = state.cChatPair;
    const { reply } = await api("/individuality-c/chat", {
      method: "POST",
      body: JSON.stringify({ personalityAId: aId, personalityBId: bId, message }),
    });
    const cBubble = document.createElement("div");
    cBubble.className = "c-chat-bubble role-c";
    cBubble.innerHTML = `<div class="c-chat-role">生まれた子</div><div>${escapeHtml(reply)}</div>`;
    log.appendChild(cBubble);
    log.scrollTop = log.scrollHeight;
  } catch (err) {
    alert(err.message);
  }
});

function renderCTimeline(history) {
  const timeline = document.getElementById("c-timeline");
  timeline.innerHTML = "";
  if (history.length === 0) {
    timeline.innerHTML = "<p>まだこのペアから生まれた子はいません。「会話させる」タブで会話させ、生み出してください。</p>";
    return;
  }
  history.slice().reverse().forEach((snapshot, idx) => {
    const card = document.createElement("div");
    card.className = "c-card";
    card.innerHTML = `
      <h3>生まれた子 スナップショット #${history.length - idx}</h3>
      <div class="c-date">${snapshot.created_at}</div>
      ${cField("対話の痕跡", snapshot.traces)}
      ${cField("差分(解消されなかった違い)", snapshot.differences)}
      ${cField("未解決の問い", snapshot.open_questions)}
      ${cField("新しい問い・第三案", snapshot.new_questions)}
      ${cField("要約", snapshot.summary)}
    `;
    timeline.appendChild(card);
  });
}

function cField(label, value) {
  return `<div class="c-field"><div class="c-field-label">${label}</div><div class="c-field-value">${escapeHtml(value || "-")}</div></div>`;
}

// ---------- 縁の地図 ----------
const SVG_NS = "http://www.w3.org/2000/svg";

function fillMapCenterSelect() {
  fillPersonalitySelects();
  const select = document.getElementById("map-center-select");
  if (!select.dataset.bound) {
    select.addEventListener("change", () => renderEnishiMap(select.value));
    select.dataset.bound = "1";
  }
  if (select.value) renderEnishiMap(select.value);
}

async function renderEnishiMap(centerId) {
  const svg = document.getElementById("enishi-svg");
  svg.innerHTML = "";
  if (!centerId) return;

  const center = state.personalities.find((p) => String(p.id) === String(centerId));
  const [relationships, influences] = await Promise.all([
    api(`/relationships/${centerId}`),
    api(`/relationships/${centerId}/influences`),
  ]);

  const cx = 320;
  const cy = 320;
  const radius = 220;
  const ghostRadius = 300;

  // 過去の出会い・経験(点線ノード)を先に描く。会話した相手の実線より外側・背面に配置する。
  influences.forEach((inf, i) => {
    const angle = (i / Math.max(influences.length, 1)) * Math.PI * 2 - Math.PI / 2 + Math.PI / (influences.length * 2 || 1);
    const x = cx + ghostRadius * Math.cos(angle);
    const y = cy + ghostRadius * Math.sin(angle);
    drawGhostEdge(svg, cx, cy, x, y, inf.influence);
    drawGhostNode(svg, x, y, inf.whoOrWhat, inf.influence, () => showInfluenceDetail(inf));
  });

  // 中心ノード
  drawNode(svg, cx, cy, center.name, true, () => showPersonDetail(center.id));

  relationships.forEach((rel, i) => {
    const angle = (i / Math.max(relationships.length, 1)) * Math.PI * 2 - Math.PI / 2;
    const x = cx + radius * Math.cos(angle);
    const y = cy + radius * Math.sin(angle);

    const label = rel.relation_label || summarizeNote(rel.notes);
    drawEdge(svg, cx, cy, x, y, label, () => showRelationshipDetail(centerId, rel.counterpart_id, rel.counterpart_name, center.name));
    drawNode(svg, x, y, rel.counterpart_name, false, () => showPersonDetail(rel.counterpart_id));
  });

  if (relationships.length === 0 && influences.length === 0) {
    showEnishiMessage("この個性にはまだ、つながりの記録がありません。「会話させる」タブで会話させるか、プロフィールに「これまでの出会いと経験」を追加してください。");
  }
}

function summarizeNote(notes) {
  if (!notes) return "";
  const firstLine = notes.split("\n").filter(Boolean)[0] || "";
  return firstLine.replace(/^- /, "").slice(0, 14);
}

function drawNode(svg, x, y, name, isCenter, onClick) {
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("class", `enishi-node${isCenter ? " center" : ""}`);
  g.addEventListener("click", onClick);

  const circle = document.createElementNS(SVG_NS, "circle");
  circle.setAttribute("cx", x);
  circle.setAttribute("cy", y);
  circle.setAttribute("r", isCenter ? 46 : 38);
  g.appendChild(circle);

  const text = document.createElementNS(SVG_NS, "text");
  text.setAttribute("x", x);
  text.setAttribute("y", y);
  text.setAttribute("text-anchor", "middle");
  text.setAttribute("dominant-baseline", "middle");
  text.textContent = name.length > 6 ? name.slice(0, 6) + "…" : name;
  g.appendChild(text);

  svg.appendChild(g);
}

function drawEdge(svg, x1, y1, x2, y2, label, onClick) {
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("class", "enishi-edge");
  g.addEventListener("click", onClick);

  const line = document.createElementNS(SVG_NS, "line");
  line.setAttribute("x1", x1);
  line.setAttribute("y1", y1);
  line.setAttribute("x2", x2);
  line.setAttribute("y2", y2);
  g.appendChild(line);

  if (label) {
    const text = document.createElementNS(SVG_NS, "text");
    text.setAttribute("x", (x1 + x2) / 2);
    text.setAttribute("y", (y1 + y2) / 2 - 6);
    text.setAttribute("text-anchor", "middle");
    text.textContent = label;
    g.appendChild(text);
  }

  svg.insertBefore(g, svg.firstChild);
}

function drawGhostNode(svg, x, y, name, influence, onClick) {
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("class", "enishi-node ghost");
  g.addEventListener("click", onClick);

  // 影響度(0〜100)を、半径18〜34px・不透明度0.35〜0.9にマッピングして視覚化する
  const r = 18 + (influence / 100) * 16;
  const opacity = 0.35 + (influence / 100) * 0.55;

  const circle = document.createElementNS(SVG_NS, "circle");
  circle.setAttribute("cx", x);
  circle.setAttribute("cy", y);
  circle.setAttribute("r", r);
  circle.setAttribute("opacity", opacity);
  g.appendChild(circle);

  const text = document.createElementNS(SVG_NS, "text");
  text.setAttribute("x", x);
  text.setAttribute("y", y);
  text.setAttribute("text-anchor", "middle");
  text.setAttribute("dominant-baseline", "middle");
  text.textContent = name.length > 5 ? name.slice(0, 5) + "…" : name;
  g.appendChild(text);

  svg.appendChild(g);
}

function drawGhostEdge(svg, x1, y1, x2, y2, influence) {
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("class", "enishi-edge ghost");

  const line = document.createElementNS(SVG_NS, "line");
  line.setAttribute("x1", x1);
  line.setAttribute("y1", y1);
  line.setAttribute("x2", x2);
  line.setAttribute("y2", y2);
  line.setAttribute("opacity", 0.25 + (influence / 100) * 0.45);
  g.appendChild(line);

  svg.insertBefore(g, svg.firstChild);
}

function showInfluenceDetail(inf) {
  const detail = document.getElementById("enishi-detail");
  const memoryItems = inf.memories
    .map(
      (m) =>
        `<div class="memory-item">${escapeHtml(m.content)}<br /><span class="memory-emotion">${escapeHtml(m.meaning || "-")}(影響度 ${m.influence})</span></div>`
    )
    .join("");
  detail.innerHTML = `
    <h3>${escapeHtml(inf.whoOrWhat)}</h3>
    <p class="hint">まだ会話はしていない・キャラクターとしては存在しない、過去の出会いや経験です。影響度: ${inf.influence}/100</p>
    <div class="score-side-label">関連する出来事</div>
    ${memoryItems}
  `;
}

function showEnishiMessage(message) {
  document.getElementById("enishi-detail").innerHTML = `<p class="hint">${escapeHtml(message)}</p>`;
}

async function showPersonDetail(personalityId) {
  const p = await api(`/personalities/${personalityId}`);
  const detail = document.getElementById("enishi-detail");
  const memoryItems = (p.memories || [])
    .slice()
    .sort((a, b) => (b.influence ?? 50) - (a.influence ?? 50))
    .map(
      (m) =>
        `<div class="memory-item">${m.who_or_what ? `<span class="memory-who-tag">${escapeHtml(m.who_or_what)}</span> ` : ""}${escapeHtml(m.content)}<br /><span class="memory-emotion">${escapeHtml(m.meaning || "-")}(影響度 ${m.influence ?? 50})</span></div>`
    )
    .join("") || '<p class="hint">まだ出会い・経験は登録されていません</p>';

  detail.innerHTML = `
    <h3>${escapeHtml(p.name)}</h3>
    <div class="c-field"><div class="c-field-label">今の気持ち・迷い</div><div class="c-field-value">${escapeHtml(p.console || "-")}</div></div>
    <div class="c-field"><div class="c-field-label">大事にしていること</div><div class="c-field-value">${escapeHtml(p.belief || "-")}</div></div>
    <div class="c-field"><div class="c-field-label">考え方のクセ</div><div class="c-field-value">${escapeHtml(p.bias || "-")}</div></div>
    <div class="score-side-label">これまでの出会いと経験</div>
    ${memoryItems}
  `;
}

async function showRelationshipDetail(centerId, counterpartId, counterpartName, centerName) {
  const pair = await api(`/relationships/pair/${centerId}/${counterpartId}`);
  const detail = document.getElementById("enishi-detail");

  const scoreBlock = (rel, label) =>
    rel
      ? `<div class="score-side-label">${label}</div>
         <div class="score-grid">
           <div class="score-box"><div class="score-label">信頼</div><div class="score-value">${rel.trust}</div></div>
           <div class="score-box"><div class="score-label">距離</div><div class="score-value">${rel.distance}</div></div>
           <div class="score-box"><div class="score-label">緊張</div><div class="score-value">${rel.tension}</div></div>
           <div class="score-box"><div class="score-label">影響</div><div class="score-value">${rel.influence}</div></div>
         </div>`
      : `<div class="score-side-label">${label}</div><p class="hint">記録なし</p>`;

  const memoryBlock = (memories, name) =>
    memories.length
      ? memories
          .map(
            (m) =>
              `<div class="memory-item"><span class="memory-emotion">${escapeHtml(m.emotion || "-")}・${m.confidence}%</span><br />${escapeHtml(m.content)}</div>`
          )
          .join("")
      : `<p class="hint">${escapeHtml(name)}側の記憶はまだありません</p>`;

  detail.innerHTML = `
    <h3>${escapeHtml(centerName)} ⇌ ${escapeHtml(counterpartName)}</h3>
    <p class="hint">同じ関係でも、双方の主観によってスコアと記憶は異なります(非対称)</p>
    ${scoreBlock(pair.aToB, `${centerName}から見たつながり`)}
    ${scoreBlock(pair.bToA, `${counterpartName}から見たつながり`)}
    <div class="score-side-label">${centerName}の主観的記憶</div>
    ${memoryBlock(pair.memoriesA, centerName)}
    <div class="score-side-label">${counterpartName}の主観的記憶</div>
    ${memoryBlock(pair.memoriesB, counterpartName)}
  `;
}

// ---------- 反応テスト ----------
function fillReactionTestSelect() {
  fillPersonalitySelects();
}

document.getElementById("reaction-test-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const personalityId = document.getElementById("rt-personality").value;
  const statusEl = document.getElementById("reaction-test-status");
  const resultsEl = document.getElementById("reaction-test-results");
  if (!personalityId) return;

  resultsEl.innerHTML = "";
  statusEl.textContent = "テストを実行中...(質問ごとにClaude APIを呼び出しています)";

  try {
    const { results } = await api(`/personalities/${personalityId}/reaction-test`, { method: "POST", body: JSON.stringify({}) });
    statusEl.textContent = `完了(${results.length}問)`;
    resultsEl.innerHTML = results
      .map(
        (r) => `<div class="rt-item"><div class="rt-question">Q. ${escapeHtml(r.question)}</div><div class="rt-answer">${escapeHtml(r.answer)}</div></div>`
      )
      .join("");
  } catch (err) {
    statusEl.textContent = "";
    alert(err.message);
  }
});

// ---------- シーン生成 ----------
document.getElementById("scene-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const personalityAId = document.getElementById("scene-personality-a").value;
  const personalityBId = document.getElementById("scene-personality-b").value;
  const situation = document.getElementById("scene-situation").value.trim();
  if (!situation) return;

  const statusEl = document.getElementById("scene-status");
  const outputEl = document.getElementById("scene-output");
  statusEl.textContent = "シーンを生成中です...(数十秒かかることがあります)";
  outputEl.innerHTML = "";

  try {
    const scene = await api("/scenes/generate", {
      method: "POST",
      body: JSON.stringify({ personalityAId, personalityBId, situation }),
    });
    statusEl.textContent = "";
    renderScene(scene);
    await loadSceneHistory(personalityAId, personalityBId);
  } catch (err) {
    statusEl.textContent = "";
    alert(err.message);
  }
});

function renderScene(scene) {
  const outputEl = document.getElementById("scene-output");
  outputEl.innerHTML = `
    <div class="scene-title">${escapeHtml(scene.title)}</div>
    <div class="scene-body">${escapeHtml(scene.content)}</div>
    <div class="scene-meta">状況: ${escapeHtml(scene.situation)} / ${scene.created_at}</div>
  `;
}

async function loadSceneHistory(personalityAId, personalityBId) {
  const historyEl = document.getElementById("scene-history");
  const list = await api(`/scenes?personalityAId=${personalityAId}&personalityBId=${personalityBId}`);
  historyEl.innerHTML = "";
  if (list.length === 0) {
    historyEl.innerHTML = '<p class="hint">まだ生成履歴はありません。</p>';
    return;
  }
  list.forEach((s) => {
    const item = document.createElement("div");
    item.className = "scene-history-item";
    item.innerHTML = `
      <div class="scene-history-title">${escapeHtml(s.title)}</div>
      <div class="scene-history-meta">${escapeHtml(s.personality_a_name)} × ${escapeHtml(s.personality_b_name)} / ${s.created_at}</div>
    `;
    item.addEventListener("click", () => renderScene(s));
    historyEl.appendChild(item);
  });
}

// ---------- 課金(ペイウォール) ----------
function showPaywall(mode = "plan") {
  document.getElementById("paywall-plan-view").style.display = mode === "plan" ? "block" : "none";
  document.getElementById("paywall-usage-view").style.display = mode === "usage" ? "block" : "none";
  document.getElementById("paywall-status").textContent = "";
  document.getElementById("paywall-overlay").style.display = "flex";
}

function hidePaywall() {
  document.getElementById("paywall-overlay").style.display = "none";
}

async function refreshBillingBadge() {
  try {
    const res = await fetch("/api/billing/status");
    const status = await res.json();
    const badge = document.getElementById("billing-badge");
    if (!status.enabled) {
      badge.style.display = "none";
      return;
    }
    badge.style.display = "inline-block";
    if (status.paid && status.usage) {
      badge.textContent = `有料プラン利用中(今月 ${status.usage.usageCount}/${status.usage.monthlyLimit}${status.usage.bonusCredits ? ` +追加${status.usage.bonusCredits}` : ""})`;
      badge.classList.add("paid");
    } else {
      badge.textContent = `未加入(¥${status.priceJpy}/月)`;
      badge.classList.remove("paid");
    }
  } catch (err) {
    // 起動直後などで失敗しても致命的ではないので無視
  }
}

document.getElementById("paywall-close-btn").addEventListener("click", hidePaywall);

document.getElementById("paywall-subscribe-btn").addEventListener("click", async () => {
  const statusEl = document.getElementById("paywall-status");
  statusEl.textContent = "決済ページを準備しています...";
  try {
    const { url } = await api("/billing/checkout", { method: "POST", body: JSON.stringify({}) });
    window.location.href = url;
  } catch (err) {
    statusEl.textContent = err.message;
  }
});

document.getElementById("paywall-topup-btn").addEventListener("click", async () => {
  const statusEl = document.getElementById("paywall-status");
  statusEl.textContent = "決済ページを準備しています...";
  try {
    const { url } = await api("/billing/topup-checkout", { method: "POST", body: JSON.stringify({}) });
    window.location.href = url;
  } catch (err) {
    statusEl.textContent = err.message;
  }
});

document.getElementById("paywall-redeem-btn").addEventListener("click", async () => {
  const input = document.getElementById("paywall-code-input");
  const statusEl = document.getElementById("paywall-status");
  const code = input.value.trim();
  if (!code) return;
  statusEl.textContent = "確認中...";
  try {
    await fetch("/api/billing/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    }).then(async (res) => {
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "コードが無効です");
    });
    statusEl.textContent = "有効化しました。";
    await refreshBillingBadge();
    setTimeout(hidePaywall, 800);
  } catch (err) {
    statusEl.textContent = err.message;
  }
});

// init
resetPersonalityForm();
loadPersonalities();
refreshBillingBadge();
