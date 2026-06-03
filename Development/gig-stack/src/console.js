const fallbackState = {
  connected: false,
  transport: "Stopped",
  venue: { console: "Console offline" },
  mix: { name: "My Mix", masterLevel: 72, masterMuted: false, assist: { detail: "Ready." } },
  session: { name: "No session" },
  channels: [],
};

const state = structuredClone(fallbackState);
const clientId = getClientId();
const params = new URLSearchParams(window.location.search);
const mixId = params.get("mixId") || clientId;

const els = {
  title: document.querySelector("#consoleTitle"),
  session: document.querySelector("#consoleSession"),
  grid: document.querySelector("#consoleGrid"),
  masterFader: document.querySelector("#consoleMasterFader"),
  masterMute: document.querySelector("#consoleMasterMuteButton"),
  back: document.querySelector("#backToGigButton"),
  assist: document.querySelector("#consoleAssistButton"),
  save: document.querySelector("#saveConsoleMixButton"),
  orb: document.querySelector("#consoleOrb"),
  form: document.querySelector("#consoleCommandForm"),
  input: document.querySelector("#consoleCommandInput"),
};

function getClientId() {
  const key = "gig-client-id";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const next = `musician-${Math.random().toString(36).slice(2, 8)}`;
  window.localStorage.setItem(key, next);
  return next;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

async function sendCommand(command) {
  const text = String(command || "").trim();
  if (!text) return;
  const response = await postJson("/api/command", { command: text, clientId, mixId });
  applyState(response.state);
}

function applyState(nextState) {
  Object.assign(state, structuredClone(nextState), { connected: true });
  render();
}

function allChannels() {
  return state.channels.flatMap((item) => [item, ...(item.children || [])]);
}

function channelCard(item) {
  const sheet = (state.mix.sheetSinks || []).includes(item.id);
  const click = (state.mix.clickSinks || []).includes(item.id);
  return `
    <article class="console-strip ${item.muted ? "muted" : ""} ${item.solo ? "soloed" : ""}">
      <div class="console-strip-head">
        <div>
          <strong>${item.name}</strong>
          <span>${item.source || "Console"}</span>
        </div>
        <output>${item.level}</output>
      </div>
      <input class="console-fader" data-level-id="${item.id}" type="range" min="0" max="100" value="${item.level}" />
      <div class="console-button-row">
        <button class="${item.muted ? "mute-active" : ""}" data-command="${item.muted ? "unmute" : "mute"} ${item.name}" type="button">Mute</button>
        <button class="${item.solo ? "solo-active" : ""}" data-command="${item.solo ? "unsolo" : "solo"} ${item.name}" type="button">Solo</button>
        <button class="${sheet ? "sync-active" : ""}" data-command="toggle sheet sink ${item.id}" type="button">Sheet</button>
        <button class="${click ? "click-active" : ""}" data-command="toggle click sink ${item.id}" type="button">Click</button>
      </div>
      <div class="console-process-row">
        <button data-command="eq ${item.name}" type="button">EQ</button>
        <button data-command="compress ${item.name}" type="button">Comp</button>
        <button data-command="console assist shape ${item.name}" type="button">AI</button>
      </div>
    </article>
  `;
}

function render() {
  els.title.textContent = state.mix.name || "My Mix";
  els.session.textContent = state.session.name || "No session";
  els.masterFader.value = state.mix.masterLevel ?? 72;
  els.masterMute.classList.toggle("mute-active", Boolean(state.mix.masterMuted));
  els.masterMute.textContent = "Mute";
  els.grid.innerHTML = allChannels().map(channelCard).join("");

  els.grid.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => sendCommand(button.dataset.command));
  });

  els.grid.querySelectorAll("[data-level-id]").forEach((slider) => {
    slider.addEventListener("change", () => {
      const channel = allChannels().find((item) => item.id === slider.dataset.levelId);
      if (channel) sendCommand(`set ${channel.name} level ${slider.value}`);
    });
  });
}

els.back.addEventListener("click", () => {
  window.location.href = "/";
});

els.assist.addEventListener("click", () => sendCommand("console assist listen"));
els.save.addEventListener("click", () => sendCommand("save this mix"));
els.masterFader.addEventListener("change", () => sendCommand(`set master level ${els.masterFader.value}`));
els.masterMute.addEventListener("click", () => sendCommand(`${state.mix.masterMuted ? "unmute" : "mute"} master`));
els.orb.addEventListener("click", () => sendCommand("console assist listen"));
els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const command = els.input.value.trim();
  els.input.value = "";
  sendCommand(command);
});

async function loadState() {
  const response = await fetch("/api/state", { cache: "no-store" });
  applyState(await response.json());
}

function connectEvents() {
  try {
    const events = new EventSource("/api/events");
    events.onmessage = (event) => applyState(JSON.parse(event.data));
    events.onerror = () => events.close();
  } catch {
    window.setInterval(loadState, 2000);
  }
}

loadState();
connectEvents();
