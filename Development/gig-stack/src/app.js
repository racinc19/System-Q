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
    clickOn: false,
    sheetsOpen: false,
    console: "Personal Console",
    consoleOpen: false,
    venueConsoleAssigned: false,
    venueConsoleOpen: false,
    assist: { name: "Console Assist", mode: "Offline", detail: "Waiting for Venue." },
  },
  session: { name: "No session", mixed: false, notes: "", takes: [] },
  activeSetId: "",
  activeSheetId: "",
  sessions: [],
  sheets: [],
  channels: [],
  sets: [],
  log: [],
};

const state = structuredClone(fallbackState);
const selectedBuildSongIds = new Set();
let editingSessionId = "";
let sessionTapTimer = 0;
let editingSetId = "";
let setTapTimer = 0;
let addingSetSongs = false;

const els = {
  venueStatus: document.querySelector("#venueStatus"),
  consoleStatus: document.querySelector("#consoleStatus"),
  transportStatus: document.querySelector("#transportStatus"),
  syncStatus: document.querySelector("#syncStatus"),
  sessionName: document.querySelector("#sessionName"),
  sessionNoteInput: document.querySelector("#sessionNoteInput"),
  saveSessionNoteButton: document.querySelector("#saveSessionNoteButton"),
  venueNote: document.querySelector("#venueNote"),
  mixName: document.querySelector("#mixName"),
  assistStatus: document.querySelector("#assistStatus"),
  consoleState: document.querySelector("#consoleState"),
  clickStatus: document.querySelector("#clickStatus"),
  sessionViewButton: document.querySelector("#sessionViewButton"),
  setViewButton: document.querySelector("#setViewButton"),
  sheetsViewButton: document.querySelector("#sheetsViewButton"),
  newSessionButton: document.querySelector("#newSessionButton"),
  newSessionPanel: document.querySelector("#newSessionPanel"),
  newSessionNameInput: document.querySelector("#newSessionNameInput"),
  createSessionButton: document.querySelector("#createSessionButton"),
  cancelNewSessionButton: document.querySelector("#cancelNewSessionButton"),
  editSessionPanel: document.querySelector("#editSessionPanel"),
  editSessionNameInput: document.querySelector("#editSessionNameInput"),
  saveSessionTitleButton: document.querySelector("#saveSessionTitleButton"),
  cancelEditSessionButton: document.querySelector("#cancelEditSessionButton"),
  buildSetViewButton: document.querySelector("#buildSetViewButton"),
  editSetPanel: document.querySelector("#editSetPanel"),
  editSetNameInput: document.querySelector("#editSetNameInput"),
  saveSetTitleButton: document.querySelector("#saveSetTitleButton"),
  cancelEditSetButton: document.querySelector("#cancelEditSetButton"),
  addSetSongsButton: document.querySelector("#addSetSongsButton"),
  addSetSongsPanel: document.querySelector("#addSetSongsPanel"),
  editSetSongs: document.querySelector("#editSetSongs"),
  availableSetSongs: document.querySelector("#availableSetSongs"),
  sessionView: document.querySelector("#sessionView"),
  setView: document.querySelector("#setView"),
  buildSetView: document.querySelector("#buildSetView"),
  sheetsView: document.querySelector("#sheetsView"),
  closeSessionViewButton: document.querySelector("#closeSessionViewButton"),
  closeSetViewButton: document.querySelector("#closeSetViewButton"),
  closeBuildSetViewButton: document.querySelector("#closeBuildSetViewButton"),
  closeSheetsViewButton: document.querySelector("#closeSheetsViewButton"),
  sessionList: document.querySelector("#sessionList"),
  setList: document.querySelector("#setList"),
  activeSetSongs: document.querySelector("#activeSetSongs"),
  buildSongList: document.querySelector("#buildSongList"),
  buildSetNameInput: document.querySelector("#buildSetNameInput"),
  sheetsList: document.querySelector("#sheetsList"),
  saveBuiltSetButton: document.querySelector("#saveBuiltSetButton"),
  channelGrid: document.querySelector("#channelGrid"),
  masterFader: document.querySelector("#masterFader"),
  masterMuteButton: document.querySelector("#masterMuteButton"),
  voiceOrb: document.querySelector("#voiceOrb"),
  commandForm: document.querySelector("#commandForm"),
  commandInput: document.querySelector("#commandInput"),
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

function songCount(songs) {
  return Array.isArray(songs) ? songs.length : Number(songs || 0);
}

function renderStatus() {
  els.venueStatus.textContent = state.venue.connected ? "Venue connected" : "Venue offline";
  els.consoleStatus.textContent = state.venue.console || "Console idle";
  els.transportStatus.textContent = state.transport;
  els.syncStatus.textContent = state.connected ? "Synced" : "Local";
  els.sessionName.textContent = state.session.name;
  if (document.activeElement !== els.sessionNoteInput) {
    els.sessionNoteInput.value = state.session.notes || "";
  }
  els.venueNote.textContent = state.venue.note;
  els.mixName.textContent = state.mix.name;
  els.assistStatus.textContent = state.mix.sheetsOpen ? "Sheets" : state.mix.assist.mode;
  els.clickStatus.textContent = state.mix.clickOn ? "Click On" : "Click Off";
  els.consoleState.textContent = state.mix.venueConsoleOpen
    ? "Venue Console"
    : state.mix.consoleOpen
      ? state.mix.console
      : "Faders";
  els.masterFader.value = state.mix.masterLevel;
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
        <button class="${item.muted ? "active mute-active" : ""}" type="button" data-command="${item.muted ? "unmute" : "mute"} ${item.name}">Mute</button>
        <button class="${item.solo ? "active solo-active" : ""}" type="button" data-command="${item.solo ? "unsolo" : "solo"} ${item.name}">Solo</button>
      </div>
      <div class="channel-badges">${badges.map((badge) => `<span>${badge}</span>`).join("")}</div>
    </article>
  `;
}

function renderSessionList() {
  els.sessionList.innerHTML = state.sessions
    .map(
      (session) => `
        <button class="session-card ${session.id === state.session.id ? "active" : ""}" type="button" data-session-id="${session.id}">
          <div>
            <strong>${session.name}</strong>
            <span>${session.type} / ${session.updated}</span>
          </div>
          <small>${session.song?.status || "song"}</small>
          <p>${session.notes}</p>
        </button>
      `,
    )
    .join("");

  els.sessionList.querySelectorAll("[data-session-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const session = state.sessions.find((item) => item.id === button.dataset.sessionId);
      if (!session) return;
      if (sessionTapTimer) {
        window.clearTimeout(sessionTapTimer);
        sessionTapTimer = 0;
        openSessionEditor(session);
        return;
      }
      sessionTapTimer = window.setTimeout(async () => {
        sessionTapTimer = 0;
        await sendCommand(`open session ${button.dataset.sessionId}`);
        closeScreenViews();
      }, 260);
    });
  });
}

function openSessionEditor(session) {
  editingSessionId = session.id;
  els.newSessionPanel.hidden = true;
  els.editSessionPanel.hidden = false;
  els.editSessionNameInput.value = session.name;
  els.editSessionNameInput.focus();
  els.editSessionNameInput.select();
}

function renderSetList() {
  els.setList.innerHTML = state.sets
    .map(
      (set) => `
        <button class="session-card ${set.id === state.activeSetId ? "active" : ""}" type="button" data-set-id="${set.id}">
          <div>
            <strong>${set.name}</strong>
            <span>${set.type} / ${set.updated}</span>
          </div>
          <small>${songCount(set.songs)} songs</small>
          <p>${set.notes}</p>
        </button>
      `,
    )
    .join("");

  els.setList.querySelectorAll("[data-set-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const set = state.sets.find((item) => item.id === button.dataset.setId);
      if (!set) return;
      if (setTapTimer) {
        window.clearTimeout(setTapTimer);
        setTapTimer = 0;
        openSetEditor(set);
        return;
      }
      setTapTimer = window.setTimeout(async () => {
        setTapTimer = 0;
        await sendCommand(`open set ${button.dataset.setId}`);
        openScreenView(els.setView);
      }, 260);
    });
  });
}

function openSetEditor(set) {
  editingSetId = set.id;
  addingSetSongs = false;
  els.editSetNameInput.value = set.name;
  enterSetEditMode();
  els.editSetNameInput.focus();
  els.editSetNameInput.select();
}

function enterSetEditMode() {
  els.sessionView.hidden = true;
  els.buildSetView.hidden = true;
  els.sheetsView.hidden = true;
  els.setView.hidden = false;
  els.setView.classList.add("editing");
  els.editSetPanel.hidden = false;
  els.addSetSongsPanel.hidden = !addingSetSongs;
  document.body.classList.add("screen-open");
  renderEditSetSongs();
}

function exitSetEditMode() {
  editingSetId = "";
  addingSetSongs = false;
  els.editSetNameInput.value = "";
  els.editSetPanel.hidden = true;
  els.addSetSongsPanel.hidden = true;
  els.setView.classList.remove("editing");
}

function renderActiveSetSongs() {
  const activeSet = state.sets.find((set) => set.id === state.activeSetId);
  const songs = activeSet?.songs || [];

  els.activeSetSongs.innerHTML = activeSet
    ? `
      <div class="set-song-head">
        <div>
          <p class="eyebrow">Songs</p>
          <h3>${activeSet.name}</h3>
        </div>
        <small>${songCount(songs)} songs</small>
      </div>
      <div class="session-list compact-list">
        ${
          songs.length
            ? songs.map((songItem) => `
              <button class="session-card song-card" type="button" data-sheet-name="${songItem.name}">
                <div>
                  <strong>${songItem.name}</strong>
                  <span>${songItem.status} / ${songItem.length}</span>
                </div>
                <small>${songItem.key} / ${songItem.tempo}</small>
                <p>Sheets ${songItem.sheets ? "ready" : "missing"} / Click ${songItem.click ? "on" : "off"} / Mix ${songItem.mixSaved ? "saved" : "rough"}</p>
              </button>
            `).join("")
            : `<p class="empty-note">No songs attached to this set.</p>`
        }
      </div>
    `
    : `<p class="empty-note">Choose a set to see its songs.</p>`;
}

function renderEditSetSongs() {
  const set = state.sets.find((item) => item.id === editingSetId);
  const setSongs = set?.songs || [];
  const setSongIds = new Set(setSongs.map((item) => item.id));
  const availableSessions = (state.sessions || []).filter((session) => !setSongIds.has(session.song?.id || session.id));

  els.editSetSongs.innerHTML = set
    ? `
      <p class="empty-note">Tap a song to remove it from this set.</p>
      ${
        setSongs.length
          ? setSongs.map((songItem) => `
            <button class="session-card song-card remove-card" type="button" data-remove-set-song-id="${songItem.id}">
              <div>
                <strong>${songItem.name}</strong>
                <span>${songItem.status} / ${songItem.length}</span>
              </div>
              <small>Remove</small>
              <p>${songItem.key} / ${songItem.tempo}</p>
            </button>
          `).join("")
          : `<p class="empty-note">No songs in this set.</p>`
      }
    `
    : "";

  els.availableSetSongs.innerHTML = availableSessions.length
    ? availableSessions.map((session) => {
      const songItem = session.song || { name: session.name, key: "-", tempo: 0, status: "ready", length: "--" };
      return `
        <button class="session-card song-card add-card" type="button" data-add-set-session-id="${session.id}">
          <div>
            <strong>${songItem.name}</strong>
            <span>${songItem.status} / ${songItem.length}</span>
          </div>
          <small>Add</small>
          <p>${songItem.key} / ${songItem.tempo}</p>
        </button>
      `;
    }).join("")
    : `<p class="empty-note">All session songs are already in this set.</p>`;

  els.editSetSongs.querySelectorAll("[data-remove-set-song-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await sendCommand(`remove set song ${editingSetId} :: ${button.dataset.removeSetSongId}`);
      addingSetSongs = false;
      enterSetEditMode();
    });
  });

  els.availableSetSongs.querySelectorAll("[data-add-set-session-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await sendCommand(`add set songs ${editingSetId} :: ${button.dataset.addSetSessionId}`);
      addingSetSongs = true;
      enterSetEditMode();
    });
  });
}

function renderBuildSongList() {
  const sessions = state.sessions || [];
  els.buildSongList.innerHTML = sessions.length
    ? sessions
      .map(
        (session) => {
          const songItem = session.song || { name: session.name, key: "-", tempo: 0, status: "ready", length: "--", sheets: true, click: false, mixSaved: false };
          return `
          <button class="session-card song-card ${selectedBuildSongIds.has(session.id) ? "active" : ""}" type="button" data-build-song-id="${session.id}">
            <div>
              <strong>${songItem.name}</strong>
              <span>${songItem.status} / ${songItem.length}</span>
            </div>
            <small>${songItem.key} / ${songItem.tempo}</small>
            <p>Sheets ${songItem.sheets ? "ready" : "missing"} / Click ${songItem.click ? "on" : "off"} / Mix ${songItem.mixSaved ? "saved" : "rough"}</p>
          </button>
        `;
        },
      )
      .join("")
    : `<p class="empty-note">No sessions yet.</p>`;

  els.buildSongList.querySelectorAll("[data-build-song-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.buildSongId;
      if (selectedBuildSongIds.has(id)) selectedBuildSongIds.delete(id);
      else selectedBuildSongIds.add(id);
      renderBuildSongList();
    });
  });
}

function renderSheetsList() {
  els.sheetsList.innerHTML = state.sheets
    .map(
      (sheet) => `
        <button class="session-card ${sheet.id === state.activeSheetId ? "active" : ""}" type="button" data-sheet-id="${sheet.id}">
          <div>
            <strong>${sheet.name}</strong>
            <span>${sheet.type} / ${sheet.updated}</span>
          </div>
          <small>${sheet.key}</small>
          <p>${sheet.notes}</p>
        </button>
      `,
    )
    .join("");

  els.sheetsList.querySelectorAll("[data-sheet-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      await sendCommand(`open sheet ${button.dataset.sheetId}`);
      closeScreenViews();
    });
  });
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

function render() {
  renderStatus();
  renderSessionList();
  renderSetList();
  renderActiveSetSongs();
  renderEditSetSongs();
  renderBuildSongList();
  renderSheetsList();
  renderChannels();
}

function openScreenView(view) {
  closeScreenViews();
  view.hidden = false;
  document.body.classList.add("screen-open");
}

function closeScreenViews() {
  if (sessionTapTimer) {
    window.clearTimeout(sessionTapTimer);
    sessionTapTimer = 0;
  }
  if (setTapTimer) {
    window.clearTimeout(setTapTimer);
    setTapTimer = 0;
  }
  els.sessionView.hidden = true;
  els.setView.hidden = true;
  els.buildSetView.hidden = true;
  els.sheetsView.hidden = true;
  els.newSessionPanel.hidden = true;
  els.editSessionPanel.hidden = true;
  els.editSetPanel.hidden = true;
  els.addSetSongsPanel.hidden = true;
  els.setView.classList.remove("editing");
  document.body.classList.remove("screen-open");
}

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => sendCommand(button.dataset.command));
});

document.querySelectorAll("[data-session-command]").forEach((button) => {
  button.addEventListener("click", async () => {
    await sendCommand(button.dataset.sessionCommand);
    closeScreenViews();
  });
});

document.querySelectorAll("[data-set-command]").forEach((button) => {
  button.addEventListener("click", async () => {
    await sendCommand(button.dataset.setCommand);
    closeScreenViews();
  });
});

els.sessionViewButton.addEventListener("click", () => openScreenView(els.sessionView));
els.setViewButton.addEventListener("click", () => openScreenView(els.setView));
els.sheetsViewButton.addEventListener("click", () => openScreenView(els.sheetsView));
els.saveSessionNoteButton.addEventListener("click", () => {
  sendCommand(`set session note ${els.sessionNoteInput.value.trim()}`);
});
els.newSessionButton.addEventListener("click", () => {
  els.editSessionPanel.hidden = true;
  els.newSessionPanel.hidden = false;
  els.newSessionNameInput.value = "";
  els.newSessionNameInput.focus();
});
els.createSessionButton.addEventListener("click", async () => {
  const name = els.newSessionNameInput.value.trim();
  await sendCommand(`new session ${name}`);
  els.newSessionNameInput.value = "";
  els.newSessionPanel.hidden = true;
  openScreenView(els.sessionView);
});
els.cancelNewSessionButton.addEventListener("click", () => {
  els.newSessionNameInput.value = "";
  els.newSessionPanel.hidden = true;
});
els.saveSessionTitleButton.addEventListener("click", async () => {
  const name = els.editSessionNameInput.value.trim();
  if (!editingSessionId || !name) return;
  await sendCommand(`rename session ${editingSessionId} :: ${name}`);
  editingSessionId = "";
  els.editSessionNameInput.value = "";
  els.editSessionPanel.hidden = true;
  openScreenView(els.sessionView);
});
els.cancelEditSessionButton.addEventListener("click", () => {
  editingSessionId = "";
  els.editSessionNameInput.value = "";
  els.editSessionPanel.hidden = true;
});
els.editSessionNameInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") els.saveSessionTitleButton.click();
  if (event.key === "Escape") els.cancelEditSessionButton.click();
});
els.newSessionNameInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") els.createSessionButton.click();
  if (event.key === "Escape") els.cancelNewSessionButton.click();
});
els.buildSetViewButton.addEventListener("click", () => {
  els.editSetPanel.hidden = true;
  selectedBuildSongIds.clear();
  (state.sessions || []).forEach((session) => selectedBuildSongIds.add(session.id));
  els.buildSetNameInput.value = `${state.session.name} Set`;
  renderBuildSongList();
  openScreenView(els.buildSetView);
});
els.saveSetTitleButton.addEventListener("click", async () => {
  const name = els.editSetNameInput.value.trim();
  if (!editingSetId || !name) return;
  await sendCommand(`rename set ${editingSetId} :: ${name}`);
  addingSetSongs = false;
  enterSetEditMode();
});
els.cancelEditSetButton.addEventListener("click", () => {
  exitSetEditMode();
});
els.addSetSongsButton.addEventListener("click", () => {
  addingSetSongs = !addingSetSongs;
  enterSetEditMode();
});
els.editSetNameInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") els.saveSetTitleButton.click();
  if (event.key === "Escape") els.cancelEditSetButton.click();
});
els.closeSessionViewButton.addEventListener("click", closeScreenViews);
els.closeSetViewButton.addEventListener("click", closeScreenViews);
els.closeBuildSetViewButton.addEventListener("click", closeScreenViews);
els.closeSheetsViewButton.addEventListener("click", closeScreenViews);
els.saveBuiltSetButton.addEventListener("click", async () => {
  if (!selectedBuildSongIds.size) {
    els.assistStatus.textContent = "Pick at least one song";
    return;
  }
  const name = els.buildSetNameInput.value.trim() || `${state.session.name} Set`;
  await sendCommand(`build set ${name} :: ${[...selectedBuildSongIds].join(",")}`);
  openScreenView(els.setView);
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
