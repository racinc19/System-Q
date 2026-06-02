const fallbackState = {
  connected: false,
  transport: "Stopped",
  venue: {
    connected: false,
    rig: "Venue box",
    console: "Console offline",
    hardware: "No rig",
    note: "Waiting for Venue.",
  },
  mix: {
    name: "My Mix",
    masterLevel: 72,
    masterMuted: false,
    console: "Personal Console",
    consoleOpen: false,
    venueConsoleAssigned: false,
    venueConsoleOpen: false,
    assist: { name: "Console Assist", mode: "Offline", detail: "Waiting for Venue." },
  },
  session: { name: "No session", mixed: false, takes: [] },
  channels: [],
  sets: [],
  log: [],
};

const state = structuredClone(fallbackState);

const els = {
  venueStatus: document.querySelector("#venueStatus"),
  consoleStatus: document.querySelector("#consoleStatus"),
  transportStatus: document.querySelector("#transportStatus"),
  syncStatus: document.querySelector("#syncStatus"),
  sessionName: document.querySelector("#sessionName"),
  venueNote: document.querySelector("#venueNote"),
  mixName: document.querySelector("#mixName"),
  assistStatus: document.querySelector("#assistStatus"),
  assistDetail: document.querySelector("#assistDetail"),
  consoleState: document.querySelector("#consoleState"),
  channelGrid: document.querySelector("#channelGrid"),
  masterFader: document.querySelector("#masterFader"),
  masterMuteButton: document.querySelector("#masterMuteButton"),
  voiceOrb: document.querySelector("#voiceOrb"),
  takesList: document.querySelector("#takesList"),
  setList: document.querySelector("#setList"),
  commandForm: document.querySelector("#commandForm"),
  commandInput: document.querySelector("#commandInput"),
  commandLog: document.querySelector("#commandLog"),
};

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

function applyServerState(nextState) {
  Object.assign(state, structuredClone(nextState), { connected: true });
  render();
}

async function sendCommand(command) {
  if (!command.trim() || !state.connected) return;
  const response = await postJson("/api/command", { command });
  applyServerState(response.state);
}

function renderStatus() {
  els.venueStatus.textContent = state.venue.connected ? "Venue connected" : "Venue offline";
  els.consoleStatus.textContent = state.venue.console || "Console idle";
  els.transportStatus.textContent = state.transport;
  els.syncStatus.textContent = state.connected ? "Synced" : "Local";
  els.sessionName.textContent = state.session.name;
  els.venueNote.textContent = state.venue.note;
  els.mixName.textContent = state.mix.name;
  els.assistStatus.textContent = `${state.mix.assist.name}: ${state.mix.assist.mode}`;
  els.assistDetail.textContent = state.mix.assist.detail;
  els.consoleState.textContent = state.mix.venueConsoleOpen
    ? "Venue Console"
    : state.mix.consoleOpen
      ? state.mix.console
      : "Faders";
  els.masterFader.value = state.mix.masterLevel;
  els.masterMuteButton.textContent = state.mix.masterMuted ? "Unmute" : "Mute";
  els.masterMuteButton.classList.toggle("active", state.mix.masterMuted);
}

function channelStrip(item, extraClass = "") {
  const badges = [
    item.muted ? "Muted" : "",
    item.solo ? "Solo" : "",
  ].filter(Boolean);

  return `
    <article class="channel-strip ${extraClass} ${item.muted ? "muted" : ""} ${item.solo ? "solo" : ""}">
      <div class="channel-top">
        <div>
          <strong>${item.name}</strong>
          <span>${item.source}</span>
        </div>
        ${item.children ? `<button type="button" data-command="${item.expanded ? "close drums" : "open drums"}">${item.expanded ? "Fold" : "Open"}</button>` : ""}
      </div>
      <input class="fader" type="range" min="0" max="100" value="${item.level}" data-level-id="${item.id}" aria-label="${item.name} fader" />
      <div class="channel-actions">
        <button type="button" data-command="${item.muted ? "unmute" : "mute"} ${item.name}">${item.muted ? "Unmute" : "Mute"}</button>
        <button type="button" data-command="${item.solo ? "unsolo" : "solo"} ${item.name}">${item.solo ? "Unsolo" : "Solo"}</button>
      </div>
      <div class="channel-badges">${badges.map((badge) => `<span>${badge}</span>`).join("")}</div>
    </article>
  `;
}

function renderChannels() {
  els.channelGrid.innerHTML = state.channels
    .map((item) => {
      const parent = channelStrip(item, item.type || "");
      const children = item.expanded && item.children
        ? `<div class="drum-children">${item.children.map((child) => channelStrip(child, "drum-child")).join("")}</div>`
        : "";
      return `${parent}${children}`;
    })
    .join("");

  els.channelGrid.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => sendCommand(button.dataset.command));
  });

  els.channelGrid.querySelectorAll("[data-level-id]").forEach((slider) => {
    slider.addEventListener("change", () => {
      const channel = findChannel(slider.dataset.levelId);
      if (!channel) return;
      sendCommand(`set ${channel.name} level ${slider.value}`);
    });
  });
}

function findChannel(id) {
  return state.channels.flatMap((item) => [item, ...(item.children || [])]).find((item) => item.id === id);
}

function renderTakesAndSets() {
  els.takesList.innerHTML = state.session.takes.length
    ? state.session.takes.map((take) => `<article><strong>${take.name}</strong><span>${take.status}</span></article>`).join("")
    : `<p class="empty-note">Recorded takes show up here.</p>`;

  els.setList.innerHTML = state.sets.length
    ? state.sets.map((set) => `<article><strong>${set.name}</strong><span>${set.takes} takes</span></article>`).join("")
    : `<p class="empty-note">Finished sessions move here as sets.</p>`;
}

function renderLog() {
  els.commandLog.innerHTML = state.log
    .map((entry) => `<li><strong>${entry.command}</strong><span>${entry.result}</span></li>`)
    .join("");
}

function render() {
  renderStatus();
  renderChannels();
  renderTakesAndSets();
  renderLog();
}

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => sendCommand(button.dataset.command));
});

els.masterFader.addEventListener("change", () => sendCommand(`set master level ${els.masterFader.value}`));
els.masterMuteButton.addEventListener("click", () => sendCommand(`${state.mix.masterMuted ? "unmute" : "mute"} master`));
els.voiceOrb.addEventListener("click", () => {
  els.voiceOrb.classList.add("listening");
  sendCommand("console assist listen");
  window.setTimeout(() => els.voiceOrb.classList.remove("listening"), 900);
});

els.commandForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendCommand(els.commandInput.value);
  els.commandInput.value = "";
});

async function connectToVenue() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error("Venue server not available.");
    applyServerState(await response.json());

    const events = new EventSource("/api/events");
    events.onmessage = (event) => applyServerState(JSON.parse(event.data));
    events.onerror = () => {
      state.connected = false;
      render();
    };
  } catch {
    state.connected = false;
    render();
  }
}

connectToVenue();
