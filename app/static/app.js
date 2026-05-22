const $ = (id) => document.getElementById(id);

let currentSessionId = null;
let lastPlayerInput = "";
let parsedPayload = null;

function setStatus(message, isError = false) {
  const el = $("status");
  el.textContent = message;
  el.style.color = isError ? "#ff7777" : "#b7afa7";
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) {
    throw new Error(data.detail ? JSON.stringify(data.detail) : text || res.statusText);
  }
  return data;
}

async function refreshSessions() {
  const sessions = await api("/api/v1/sessions");
  const select = $("sessions");
  select.innerHTML = "";
  for (const session of sessions) {
    const option = document.createElement("option");
    option.value = session.session_id;
    option.textContent = `${session.title} · ${session.turn_number} ход · ${session.session_id}`;
    select.appendChild(option);
  }
  if (sessions.length) {
    currentSessionId = select.value || sessions[0].session_id;
    updateSessionInfo();
  } else {
    currentSessionId = null;
    $("sessionInfo").textContent = "Сессий пока нет.";
  }
}

function updateSessionInfo() {
  currentSessionId = $("sessions").value || currentSessionId;
  $("sessionInfo").textContent = currentSessionId ? `Выбрана: ${currentSessionId}` : "Сессия не выбрана.";
}

async function createSession() {
  const data = await api("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({
      title: $("title").value.trim() || "New Session",
      genre: $("genre").value.trim() || "urban mystery romance",
      player_name: $("playerName").value.trim() || "Noa Hart",
    }),
  });
  currentSessionId = data.session.session_id;
  await refreshSessions();
  $("sessions").value = currentSessionId;
  updateSessionInfo();
  setStatus("Сессия создана ✅");
}

async function buildPrompt() {
  if (!currentSessionId) throw new Error("Сначала создай или выбери сессию.");
  lastPlayerInput = $("playerInput").value.trim();
  if (!lastPlayerInput) throw new Error("Напиши действие игрока.");
  const data = await api(`/api/v1/sessions/${currentSessionId}/turns`, {
    method: "POST",
    body: JSON.stringify({ player_input: lastPlayerInput, mode: "manual_gpt" }),
  });
  $("promptOutput").value = data.prompt || "";
  setStatus("Prompt готов. Скопируй его в ChatGPT ✨");
}

async function copyPrompt() {
  const prompt = $("promptOutput").value;
  if (!prompt) throw new Error("Prompt пока пустой.");
  await navigator.clipboard.writeText(prompt);
  setStatus("Prompt скопирован ✅");
}

function extractSection(text, sectionName, nextNames = []) {
  const start = text.indexOf(sectionName);
  if (start === -1) return "";
  const contentStart = start + sectionName.length;
  let end = text.length;
  for (const next of nextNames) {
    const idx = text.indexOf(next, contentStart);
    if (idx !== -1 && idx < end) end = idx;
  }
  return text.slice(contentStart, end).trim();
}

function stripJsonFence(block) {
  return block
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/i, "")
    .replace(/```\s*$/i, "")
    .trim();
}

function safeJson(block, fallback = {}) {
  const cleaned = stripJsonFence(block);
  if (!cleaned) return fallback;
  return JSON.parse(cleaned);
}

function parseAnswer() {
  const text = $("gptAnswer").value.trim();
  if (!text) throw new Error("Вставь ответ ChatGPT.");

  const scene = extractSection(text, "## SCENE", ["## STATE_UPDATE_JSON", "STATE_UPDATE_JSON"])
    || extractSection(text, "SCENE", ["STATE_UPDATE_JSON"]);
  const stateBlock = extractSection(text, "## STATE_UPDATE_JSON", ["## KNOWLEDGE_UPDATE_JSON", "KNOWLEDGE_UPDATE_JSON"])
    || extractSection(text, "STATE_UPDATE_JSON", ["KNOWLEDGE_UPDATE_JSON"]);
  const knowledgeBlock = extractSection(text, "## KNOWLEDGE_UPDATE_JSON", ["## NPC_LIFE_UPDATE_JSON", "NPC_LIFE_UPDATE_JSON"])
    || extractSection(text, "KNOWLEDGE_UPDATE_JSON", ["NPC_LIFE_UPDATE_JSON"]);
  const npcBlock = extractSection(text, "## NPC_LIFE_UPDATE_JSON", ["## LOGIC_NOTES", "LOGIC_NOTES"])
    || extractSection(text, "NPC_LIFE_UPDATE_JSON", ["LOGIC_NOTES"]);
  const notes = extractSection(text, "## LOGIC_NOTES", []) || extractSection(text, "LOGIC_NOTES", []);

  const stateJson = safeJson(stateBlock, {});
  const knowledgeJson = safeJson(knowledgeBlock, {});
  const npcJson = safeJson(npcBlock, {});

  parsedPayload = {
    player_input: lastPlayerInput || $("playerInput").value.trim(),
    scene_text: scene,
    state_update: stateJson.state_update || stateJson,
    knowledge_update: knowledgeJson.knowledge_update || knowledgeJson,
    npc_life_update: npcJson.npc_life_update || npcJson,
    notes: notes ? [notes] : [],
  };

  $("savePreview").value = JSON.stringify(parsedPayload, null, 2);
  setStatus("Ответ разобран. Проверь preview и сохрани ✅");
}

async function saveResult() {
  if (!currentSessionId) throw new Error("Сессия не выбрана.");
  if (!parsedPayload) parseAnswer();
  if (!parsedPayload.scene_text) throw new Error("Не найден текст сцены.");
  const data = await api(`/api/v1/sessions/${currentSessionId}/manual-results`, {
    method: "POST",
    body: JSON.stringify(parsedPayload),
  });
  setStatus("Сцена сохранена в память ✅");
  $("gptAnswer").value = "";
  $("savePreview").value = "";
  parsedPayload = null;
  await refreshSessions();
  await loadSession();
  return data;
}

async function loadSession() {
  if (!currentSessionId) throw new Error("Сессия не выбрана.");
  const data = await api(`/api/v1/sessions/${currentSessionId}`);
  const lastScene = data.scene_history?.at(-1);
  $("memoryView").textContent = JSON.stringify({
    session: data.session,
    current_state: data.current_state,
    last_scene: lastScene || null,
    known_by_player: data.knowledge_map?.player || null,
  }, null, 2);
  setStatus("Память загружена.");
}

function bind(id, event, handler) {
  $(id).addEventListener(event, async () => {
    try { await handler(); }
    catch (err) { setStatus(err.message, true); }
  });
}

bind("refreshSessions", "click", refreshSessions);
bind("createSession", "click", createSession);
bind("buildPrompt", "click", buildPrompt);
bind("copyPrompt", "click", copyPrompt);
bind("parseAnswer", "click", parseAnswer);
bind("saveResult", "click", saveResult);
bind("loadSession", "click", loadSession);
$("sessions").addEventListener("change", updateSessionInfo);

refreshSessions().catch((err) => setStatus(err.message, true));
