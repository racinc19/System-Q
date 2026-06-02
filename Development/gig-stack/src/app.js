const fallbackState = {
  connected: false,
  transport: "Stopped",
  venue: {
    connected: true,
    rig: "Akai EIE USB",
    setupName: "",
    inputs: [
      { id: "input-1", label: "Input 1", level: 58, muted: false },
      { id: "input-2", label: "Input 2", level: 54, muted: false },
      { id: "input-3", label: "Input 3", level: 50, muted: false },
      { id: "input-4", label: "Input 4", level: 50, muted: false },
    ],
    outputs: [
      { id: "phones", label: "phones", level: 62, muted: false },
      { id: "main", label: "main", level: 45, muted: false },
    ],
  },
  session: {
    id: "session-1",
    name: "Untitled Session",
    mixed: false,
    selectedTrackId: "track-1",
    tracks: [
      {
        id: "track-1",
        name: "Vocal",
        inputId: "input-1",
        status: "ready",
        note: "",
        level: 60,
        muted: false,
        solo: false,
        armed: false,
        takes: 0,
        eq: { enabled: false, tone: "flat", lowCut: false },
        comp: { enabled: false, amount: "off" },
        reverb: { enabled: false, amount: "dry" },
      },
    ],
  },
  sets: [],
  log: [],
};

const state = structuredClone(fallbackState);

const els = {
  venueStatus: document.querySelector("#venueStatus"),
  consoleStatus: document.querySelector("#consoleStatus"),
  transportStatus: document.querySelector("#transportStatus"),
  sessionName: document.querySelector("#sessionName"),
  bandPlan: document.querySelector("#bandPlan"),
  trackList: document.querySelector("#trackList"),
  setList: document.querySelector("#setList"),
  selectedTrackTitle: document.querySelector("#selectedTrackTitle"),
  akaiStatus: document.querySelector("#akaiStatus"),
  setupStatus: document.querySelector("#setupStatus"),
  outputsStatus: document.querySelector("#outputsStatus"),
  inputSummary: document.querySelector("#inputSummary"),
  akaiInputs: document.querySelector("#akaiInputs"),
  trackLevel: document.querySelector("#trackLevel"),
  trackLevelOutput: document.querySelector("#trackLevelOutput"),
  muteTrackButton: document.querySelector("#muteTrackButton"),
  soloTrackButton: document.querySelector("#soloTrackButton"),
  armTrackButton: document.querySelector("#armTrackButton"),
  trackDetail: document.querySelector("#trackDetail"),
  stackSync: document.querySelector("#stackSync"),
  commandForm: document.querySelector("#commandForm"),
  commandInput: document.querySelector("#commandInput"),
  commandLog: document.querySelector("#commandLog"),
};

function selectedTrack() {
  return state.session.tracks.find((track) => track.id === state.session.selectedTrackId) || state.session.tracks[0] || null;
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

function applyServerState(nextState) {
  Object.assign(state, structuredClone(nextState), { connected: true });
  render();
}

async function sendCommand(command) {
  if (!command.trim()) return;
  if (!state.connected) return;
  const response = await postJson("/api/command", { command });
  applyServerState(response.state);
}

function renderStatus() {
  els.venueStatus.textContent = state.venue.connected ? "Venue connected" : "Venue offline";
  els.consoleStatus.textContent = state.session.tracks.length ? "Console ready" : "Console idle";
  els.transportStatus.textContent = state.transport;
  els.stackSync.textContent = state.connected ? "Synced" : "Local";
  els.sessionName.textContent = state.session.name;
}

function renderTracks() {
  els.trackList.innerHTML = state.session.tracks
    .map(
      (track) => `
        <button class="track-item ${track.id === state.session.selectedTrackId ? "active" : ""}" type="button" data-track-id="${track.id}">
          <strong>${track.name}</strong>
          <span>${track.status === "waiting" ? "waiting for input" : track.inputId} ${track.armed ? "armed" : ""} ${track.muted ? "muted" : ""}</span>
        </button>
      `,
    )
    .join("");

  els.trackList.querySelectorAll("[data-track-id]").forEach((button) => {
    button.addEventListener("click", () => sendCommand(`select ${button.dataset.trackId}`));
  });

  els.setList.innerHTML = state.sets.length
    ? state.sets.map((set) => `<article class="set-item"><strong>${set.name}</strong><span>${set.tracks} tracks</span></article>`).join("")
    : `<p class="empty-note">Mixed sessions land here as sets.</p>`;
}

function renderBandPlan() {
  const desired = ["Drums", "Bass", "Guitar", "Vocal", "Acoustic Guitar"];
  els.bandPlan.innerHTML = desired
    .map((name) => {
      const track = state.session.tracks.find((candidate) => candidate.name === name);
      const status = track
        ? track.status === "waiting"
          ? "Waiting"
          : track.inputId
        : "Not added";
      return `
        <article class="${track?.status === "waiting" ? "waiting" : track ? "ready" : ""}">
          <strong>${name}</strong>
          <span>${status}</span>
        </article>
      `;
    })
    .join("");
}

function renderVenue() {
  els.akaiStatus.textContent = `${state.venue.rig} ${state.venue.connected ? "ready" : "idle"}`;
  els.setupStatus.textContent = state.venue.setupName || "No saved setup";
  els.outputsStatus.textContent = state.venue.outputs
    .map((output) => `${output.label} ${output.muted ? "muted" : output.level}`)
    .join(" / ");
  els.inputSummary.innerHTML = state.venue.inputs
    .map((input) => {
      const track = state.session.tracks.find((candidate) => candidate.inputId === input.id);
      return `<span>${input.id}: ${track ? track.name : "open"}</span>`;
    })
    .join("");

  els.akaiInputs.innerHTML = state.venue.inputs
    .map(
      (input) => `
        <article class="akai-channel ${input.muted ? "muted" : ""}">
          <div>
            <strong>${input.label}</strong>
            <span>${input.id}</span>
          </div>
          <meter min="0" max="100" value="${input.muted ? 0 : input.level}"></meter>
          <output>${input.muted ? "Muted" : input.level}</output>
          <div class="channel-actions">
            <button type="button" data-command="make ${input.id} quieter" aria-label="Lower ${input.label}">-</button>
            <button type="button" data-command="make ${input.id} louder" aria-label="Raise ${input.label}">+</button>
            <button type="button" data-command="${input.muted ? "unmute" : "mute"} ${input.id}">${input.muted ? "Unmute" : "Mute"}</button>
          </div>
        </article>
      `,
    )
    .join("");

  els.akaiInputs.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => sendCommand(button.dataset.command));
  });
}

function renderSelectedTrack() {
  const track = selectedTrack();
  if (!track) {
    els.selectedTrackTitle.textContent = "No track selected";
    els.trackDetail.innerHTML = "";
    return;
  }

  els.selectedTrackTitle.textContent = track.name;
  els.trackLevel.value = track.level;
  els.trackLevelOutput.textContent = track.level;
  els.muteTrackButton.textContent = track.muted ? "Unmute" : "Mute";
  els.soloTrackButton.textContent = track.solo ? "Unsolo" : "Solo";
  els.armTrackButton.textContent = track.armed ? "Armed" : "Arm";

  els.trackDetail.innerHTML = `
    <article><span>Input</span><strong>${track.inputId}</strong></article>
    <article><span>Status</span><strong>${track.status === "waiting" ? "waiting" : "ready"}</strong></article>
    <article><span>Takes</span><strong>${track.takes}</strong></article>
    <article><span>EQ</span><strong>${track.eq.enabled ? `${track.eq.tone}${track.eq.lowCut ? " / low cut" : ""}` : "off"}</strong></article>
    <article><span>Compression</span><strong>${track.comp.enabled ? track.comp.amount : "off"}</strong></article>
    <article><span>Reverb</span><strong>${track.reverb.enabled ? track.reverb.amount : "dry"}</strong></article>
  `;
}

function renderLog() {
  els.commandLog.innerHTML = state.log
    .map((entry) => `<li><strong>${entry.command}</strong><span>${entry.result}</span></li>`)
    .join("");
}

function render() {
  renderStatus();
  renderBandPlan();
  renderTracks();
  renderVenue();
  renderSelectedTrack();
  renderLog();
}

document.querySelector("#newSessionButton").addEventListener("click", () => sendCommand("new session"));
document.querySelector("#addTrackButton").addEventListener("click", () => sendCommand("add track"));
document.querySelector("#moveToSetButton").addEventListener("click", () => sendCommand("move this session to set"));
document.querySelector("#recordButton").addEventListener("click", () => sendCommand("record this track"));
document.querySelector("#playButton").addEventListener("click", () => sendCommand("play"));
document.querySelector("#stopButton").addEventListener("click", () => sendCommand("stop"));
els.muteTrackButton.addEventListener("click", () => sendCommand(`${selectedTrack()?.muted ? "unmute" : "mute"} this track`));
els.soloTrackButton.addEventListener("click", () => sendCommand(`${selectedTrack()?.solo ? "unsolo" : "solo"} this track`));
els.armTrackButton.addEventListener("click", () => sendCommand("arm this track"));
els.trackLevel.addEventListener("change", () => sendCommand(`set this track level ${els.trackLevel.value}`));

els.commandForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendCommand(els.commandInput.value);
  els.commandInput.value = "";
});

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => sendCommand(button.dataset.command));
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
