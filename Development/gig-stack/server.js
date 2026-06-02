const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const PORT = Number(process.env.PORT || 4180);
const ROOT = __dirname;

const DRUM_CHILDREN = [
  channel("kick", "Kick", "input-1", 62),
  channel("snare", "Snare", "input-2", 58),
  channel("hat", "Hat", "input-3", 44),
  channel("tom-1", "Tom 1", "input-4", 50),
  channel("tom-2", "Tom 2", "input-5", 48),
  channel("oh-l", "OH L", "input-6", 52),
  channel("oh-r", "OH R", "input-7", 52),
  channel("room", "Room", "input-8", 38),
];

const SESSION_SONGS = {
  "session-1": [
    song("new-south", "New South", "G", 92, "ready", "4:12"),
    song("porch-light", "Porch Light", "D", 76, "mixed", "3:48"),
    song("river-road", "River Road", "A", 104, "rough", "4:35"),
  ],
  "session-friday": [
    song("new-south", "New South", "G", 92, "ready", "4:12"),
    song("friday-full-band", "Friday Full Band", "E", 118, "mixed", "5:04"),
    song("last-call", "Last Call", "Bm", 84, "ready", "3:57"),
    song("porch-light", "Porch Light", "D", 76, "mixed", "3:48"),
  ],
  "session-acoustic": [
    song("porch-light", "Porch Light", "D", 76, "mixed", "3:48"),
    song("new-south-acoustic", "New South Acoustic", "G", 88, "ready", "4:08"),
    song("lantern", "Lantern", "C", 72, "rough", "3:33"),
    song("sunday-room", "Sunday Room", "Am", 68, "ready", "4:21"),
  ],
  "session-writes": [
    song("river-road", "River Road", "A", 104, "rough", "4:35"),
    song("half-moon", "Half Moon", "F", 96, "rough", "3:29"),
    song("window-seat", "Window Seat", "C", 80, "ready", "3:51"),
  ],
  "session-rehearsal": [
    song("friday-full-band", "Friday Full Band", "E", 118, "mixed", "5:04"),
    song("new-south", "New South", "G", 92, "ready", "4:12"),
    song("last-call", "Last Call", "Bm", 84, "ready", "3:57"),
    song("river-road", "River Road", "A", 104, "rough", "4:35"),
    song("porch-light", "Porch Light", "D", 76, "mixed", "3:48"),
  ],
};

const state = {
  transport: "Stopped",
  venue: {
    connected: true,
    rig: "Venue box",
    console: "Console ready on Venue",
    hardware: "Akai EIE USB attached",
    note: "Venue owns inputs, house routing, and recording. This browser controls only the musician's personal mix.",
  },
  mix: {
    name: "My Mix",
    masterLevel: 72,
    masterMuted: false,
    clickOn: false,
    sheetsOpen: false,
    console: "Personal Console",
    consoleOpen: false,
    venueConsoleAssigned: true,
    venueConsoleOpen: false,
    assist: {
      name: "Console Assist",
      mode: "Listening",
      detail: "Identifying channel tone and keeping the personal mix musical.",
    },
  },
  session: {
    id: "session-1",
    name: "Untitled Session",
    mixed: false,
    notes: "Scratch pass ready.",
    takes: [
      { id: "take-1", name: "Scratch pass", status: "ready" },
    ],
    song: structuredClone(SESSION_SONGS["session-1"][0]),
  },
  activeSetId: "set-friday",
  activeSheetId: "sheet-friday-chart",
  sessions: [
    { id: "session-1", name: "Untitled Session", type: "Current", updated: "Now", song: structuredClone(SESSION_SONGS["session-1"][0]), notes: "Scratch pass ready." },
    { id: "session-friday", name: "Friday Full Band", type: "Recent", updated: "Yesterday", song: structuredClone(SESSION_SONGS["session-friday"][1]), notes: "Drums, bass, guitar, vocal, acoustic." },
    { id: "session-acoustic", name: "Acoustic Night", type: "Recent", updated: "May 31", song: structuredClone(SESSION_SONGS["session-acoustic"][1]), notes: "Vocal, acoustic, room mic, click optional." },
    { id: "session-writes", name: "Writing Room", type: "Recent", updated: "May 29", song: structuredClone(SESSION_SONGS["session-writes"][0]), notes: "Guitar ideas and vocal roughs." },
    { id: "session-rehearsal", name: "Sunday Rehearsal", type: "Archive", updated: "May 24", song: structuredClone(SESSION_SONGS["session-rehearsal"][2]), notes: "Saved personal mixes and sheets." },
  ],
  sets: [
    { id: "set-friday", name: "Friday Night Set", type: "Active", updated: "Today", songs: structuredClone(SESSION_SONGS["session-friday"]), notes: "Full band order with click and sheets ready." },
    { id: "set-acoustic", name: "Acoustic Porch Set", type: "Recent", updated: "May 31", songs: structuredClone(SESSION_SONGS["session-acoustic"]).slice(0, 3), notes: "Acoustic, vocal, light percussion." },
    { id: "set-rehearsal", name: "Rehearsal Run", type: "Draft", updated: "May 29", songs: structuredClone(SESSION_SONGS["session-rehearsal"]), notes: "Working order for new material." },
    { id: "set-encore", name: "Encore Ideas", type: "Archive", updated: "May 22", songs: structuredClone(SESSION_SONGS["session-writes"]), notes: "Loose songs with saved musician mixes." },
  ],
  sheets: [
    { id: "sheet-friday-chart", name: "Friday Full Band Chart", type: "Chart", key: "E", updated: "Today", notes: "Verse, chorus, bridge, hits, and ending." },
    { id: "sheet-new-south", name: "New South", type: "Lyrics + Chords", key: "G", updated: "Yesterday", notes: "Capo 2 acoustic chart with vocal cues." },
    { id: "sheet-acoustic-night", name: "Acoustic Night Packet", type: "Packet", key: "Mixed", updated: "May 31", notes: "Seven-song lyric packet." },
    { id: "sheet-drum-cues", name: "Drum Cues", type: "Notes", key: "-", updated: "May 30", notes: "Starts, stops, count-ins, and breaks." },
    { id: "sheet-bass-map", name: "Bass Roadmap", type: "Chart", key: "A", updated: "May 28", notes: "Arrangement map and stops." },
  ],
  channels: [
    { ...channel("drums", "Drums", "input 1-8", 64), type: "group", expanded: false, children: DRUM_CHILDREN },
    channel("bass", "Bass", "input-9", 57),
    channel("guitar", "Guitar", "input-10", 54),
    channel("vocal", "Vocal", "input-11", 61),
    channel("acoustic", "Acoustic", "input-12", 50),
  ],
  log: [],
  undoStack: [],
};

const clients = new Set();

function channel(id, name, source, level) {
  return {
    id,
    name,
    source,
    level,
    muted: false,
    solo: false,
    armed: true,
    eq: { enabled: false, tone: "flat", lowCut: false },
    comp: { enabled: false, amount: "off" },
  };
}

function song(id, name, key, tempo, status, length) {
  return {
    id,
    name,
    key,
    tempo,
    status,
    length,
    sheets: true,
    click: tempo > 0,
    mixSaved: status !== "rough",
  };
}

function clamp(value) {
  return Math.max(0, Math.min(100, Number(value)));
}

function addLog(command, result) {
  state.log.unshift({ command, result, at: new Date().toISOString() });
  state.log = state.log.slice(0, 16);
}

function snapshotUndo(label) {
  state.undoStack.push({
    label,
    transport: state.transport,
    venue: structuredClone(state.venue),
    mix: structuredClone(state.mix),
    session: structuredClone(state.session),
    activeSetId: state.activeSetId,
    activeSheetId: state.activeSheetId,
    sessions: structuredClone(state.sessions),
    channels: structuredClone(state.channels),
    sets: structuredClone(state.sets),
    sheets: structuredClone(state.sheets),
  });
  state.undoStack = state.undoStack.slice(-16);
}

function undoLast() {
  const previous = state.undoStack.pop();
  if (!previous) return "Nothing to undo.";
  state.transport = previous.transport;
  state.venue = previous.venue;
  state.mix = previous.mix;
  state.session = previous.session;
  state.activeSetId = previous.activeSetId;
  state.activeSheetId = previous.activeSheetId;
  state.sessions = previous.sessions;
  state.channels = previous.channels;
  state.sets = previous.sets;
  state.sheets = previous.sheets;
  return `Undone: ${previous.label}.`;
}

function allChannels() {
  return state.channels.flatMap((item) => [item, ...(item.children || [])]);
}

function resolveChannel(command) {
  const normalized = command.replace(/input[-\s]*(\d+)/g, "input-$1");
  const byName = allChannels().find((item) => normalized.includes(item.name.toLowerCase()));
  if (byName) return byName;

  const inputMatch = normalized.match(/\binput-(\d+)\b/);
  if (inputMatch) {
    return allChannels().find((item) => item.source === `input-${inputMatch[1]}`) || null;
  }

  if (normalized.includes("this") || normalized.includes("selected") || normalized.includes("it")) {
    return state.channels.find((item) => item.id === "vocal") || state.channels[0];
  }
  return null;
}

function createSession(name = "Untitled Session") {
  const sessionSong = song(`song-${Date.now()}`, name, "-", 0, "new", "--");
  state.transport = "Stopped";
  state.session = {
    id: `session-${Date.now()}`,
    name,
    mixed: false,
    notes: "",
    takes: [],
    song: sessionSong,
  };
  state.channels.forEach((item) => {
    item.muted = false;
    item.solo = false;
    item.armed = true;
  });
  state.mix.masterMuted = false;
  state.mix.consoleOpen = false;
  state.mix.venueConsoleOpen = false;
  state.mix.assist.mode = "Listening";
  state.mix.assist.detail = "Ready to shape the personal mix without touching the house.";
  state.sessions = [
    { id: state.session.id, name: state.session.name, type: "Current", updated: "Now", song: structuredClone(sessionSong), notes: "New session." },
    ...state.sessions.map((item) => ({ ...item, type: item.type === "Current" ? "Recent" : item.type })),
  ].slice(0, 8);
  return `New session opened. Venue kept the musician mix faders ready.`;
}

function openPreviousSession() {
  state.transport = "Stopped";
  state.session = {
    id: `session-${Date.now()}`,
    name: "Previous Session",
    mixed: false,
    notes: "Opened from the previous saved song session.",
    takes: [
      { id: "take-prev-1", name: "Full band take 1", status: "ready" },
      { id: "take-prev-2", name: "Vocal fix", status: "ready" },
      { id: "take-prev-3", name: "Acoustic overdub", status: "ready" },
    ],
    song: structuredClone(SESSION_SONGS["session-rehearsal"][0]),
  };
  return "Previous session opened. The same musician mix faders are ready.";
}

function openSessionById(id) {
  const saved = state.sessions.find((item) => item.id === id);
  if (!saved) return "Session not found.";
  state.transport = "Stopped";
  state.session = {
    id: saved.id,
    name: saved.name,
    mixed: false,
    notes: saved.notes || "",
    takes: [
      { id: `take-${saved.id}-1`, name: "Band take 1", status: "ready" },
      { id: `take-${saved.id}-2`, name: "Vocal pass", status: "ready" },
    ],
    song: structuredClone(saved.song || song(saved.id, saved.name, "-", 0, "ready", "--")),
  };
  state.sessions = [
    { ...saved, type: "Current", updated: "Now" },
    ...state.sessions.filter((item) => item.id !== id).map((item) => ({ ...item, type: item.type === "Current" ? "Recent" : item.type })),
  ];
  return `${saved.name} opened.`;
}

function renameSessionById(id, name) {
  const nextName = String(name || "").trim();
  const saved = state.sessions.find((item) => item.id === id);
  if (!saved) return "Session not found.";
  if (!nextName) return "Session title is blank.";

  const renamed = {
    ...saved,
    name: nextName,
    updated: "Now",
    song: { ...(saved.song || song(saved.id, nextName, "-", 0, "ready", "--")), name: nextName },
  };

  state.sessions = state.sessions.map((item) => (item.id === id ? renamed : item));
  if (state.session.id === id) {
    state.session.name = nextName;
    state.session.song = structuredClone(renamed.song);
  }
  return `Session renamed ${nextName}.`;
}

function openSetById(id) {
  const set = state.sets.find((item) => item.id === id);
  if (!set) return "Set not found.";
  state.activeSetId = set.id;
  state.sets = [
    { ...set, type: "Active", updated: "Now" },
    ...state.sets.filter((item) => item.id !== id).map((item) => ({ ...item, type: item.type === "Active" ? "Recent" : item.type })),
  ];
  return `${set.name} selected.`;
}

function openSheetById(id) {
  const sheet = state.sheets.find((item) => item.id === id);
  if (!sheet) return "Sheet not found.";
  state.activeSheetId = sheet.id;
  state.mix.sheetsOpen = true;
  state.sheets = [
    { ...sheet, updated: "Now" },
    ...state.sheets.filter((item) => item.id !== id),
  ];
  return `${sheet.name} opened.`;
}

function buildSetFromSession(songIds, name) {
  const requested = new Set(songIds.filter(Boolean));
  const available = state.sessions.map((session) => session.song || song(session.id, session.name, "-", 0, "ready", "--"));
  const selected = requested.size
    ? state.sessions.filter((session) => requested.has(session.id)).map((session) => session.song || song(session.id, session.name, "-", 0, "ready", "--"))
    : available;

  if (!selected.length) return "Pick at least one session song.";

  const setName = String(name || "").trim() || `${state.session.name} Set`;
  const set = {
    id: `set-${Date.now()}`,
    name: setName,
    type: "Active",
    updated: "Now",
    songs: structuredClone(selected),
    notes: "Built from selected sessions.",
  };

  state.activeSetId = set.id;
  state.sets = [
    set,
    ...state.sets.map((item) => ({ ...item, type: item.type === "Active" ? "Recent" : item.type })),
  ];
  return `${set.name} built with ${selected.length} songs.`;
}

function recordAll() {
  const armed = allChannels().filter((item) => item.armed && !item.children);
  state.transport = "Recording";
  state.session.takes.unshift({
    id: `take-${Date.now()}`,
    name: `Band take ${state.session.takes.length + 1}`,
    status: `recording ${armed.length} channels`,
  });
  return `Recording ${armed.length} Venue channels.`;
}

function setChannelLevel(item, amount) {
  item.level = clamp(item.level + amount);
  return `${item.name} is ${amount > 0 ? "up" : "down"} ${Math.abs(amount)} points.`;
}

function setChannelLevelExact(item, level) {
  item.level = clamp(level);
  return `${item.name} level set to ${item.level}.`;
}

function setMasterLevelExact(level) {
  state.mix.masterLevel = clamp(level);
  return `Master volume set.`;
}

function openPersonalConsole() {
  state.mix.consoleOpen = true;
  state.mix.venueConsoleOpen = false;
  return "Personal Console opened for this musician's mix only.";
}

function openVenueConsole() {
  if (!state.mix.venueConsoleAssigned) return "Venue Console is not assigned on this device.";
  state.mix.venueConsoleOpen = true;
  state.mix.consoleOpen = false;
  return "Assigned Venue Console opened for house and engineering control.";
}

function updateAssist(command) {
  state.mix.assist.mode = "Listening";
  if (command.includes("snare")) {
    state.mix.assist.detail = "Snare target loaded: controlled crack, less ring, fitted compression and EQ.";
    return "Console Assist is shaping the snare target.";
  }
  if (command.includes("kick")) {
    state.mix.assist.detail = "Kick target loaded: tighter low end, clear attack, controlled gate and compression.";
    return "Console Assist is shaping the kick target.";
  }
  state.mix.assist.detail = "Listening to channel tone and applying source-aware Console moves.";
  return "Console Assist is listening and shaping the mix.";
}

function requestNewTrack(command) {
  let name = "Track";
  if (command.includes("acoustic")) name = "Acoustic";
  else if (command.includes("vocal")) name = "Vocal";
  else if (command.includes("guitar")) name = "Guitar";
  else if (command.includes("bass")) name = "Bass";
  else if (command.includes("drum")) name = "Drum Overdub";
  return `${name} track requested. Waiting for Venue Console to arm.`;
}

function runCommand(rawCommand) {
  const command = String(rawCommand || "").trim().toLowerCase();
  if (!command) return { result: "No command.", changed: false };

  let result = "Command not recognized yet.";
  let changed = true;

  if (command.includes("undo")) {
    changed = false;
    result = undoLast();
  } else if (command.includes("open previous")) {
    snapshotUndo("open previous session");
    result = openPreviousSession();
  } else if (command.startsWith("open session ")) {
    snapshotUndo("open session");
    result = openSessionById(rawCommand.replace(/open session/i, "").trim());
  } else if (command.startsWith("rename session ")) {
    snapshotUndo("rename session");
    const payload = rawCommand.replace(/rename session/i, "").trim();
    const [idPart, namePart] = payload.includes("::") ? payload.split("::") : ["", payload];
    result = renameSessionById(idPart.trim(), namePart);
  } else if (command.startsWith("open set ")) {
    snapshotUndo("open set");
    result = openSetById(rawCommand.replace(/open set/i, "").trim());
  } else if (command.startsWith("open sheet ")) {
    snapshotUndo("open sheet");
    result = openSheetById(rawCommand.replace(/open sheet/i, "").trim());
  } else if (command.startsWith("build set ")) {
    snapshotUndo("build set");
    const payload = rawCommand.replace(/build set/i, "").trim();
    const [namePart, idsPart] = payload.includes("::") ? payload.split("::") : ["", payload];
    const songIds = idsPart.split(",").map((item) => item.trim());
    result = buildSetFromSession(songIds, namePart);
  } else if (command.startsWith("new session")) {
    snapshotUndo("new session");
    const name = rawCommand.replace(/new session/i, "").trim() || "Untitled Session";
    result = createSession(name);
  } else if (command.startsWith("name this session")) {
    snapshotUndo("name session");
    const name = rawCommand.replace(/name this session/i, "").trim() || "Untitled Session";
    state.session.name = name;
    state.session.song = { ...(state.session.song || song(state.session.id, name, "-", 0, "ready", "--")), name };
    state.sessions.unshift({ id: state.session.id, name, type: "Current", updated: "Now", song: state.session.song, notes: state.session.notes || "New session." });
    result = `Session named ${name}.`;
  } else if (command.startsWith("set session note ")) {
    snapshotUndo("set session note");
    const note = rawCommand.replace(/set session note/i, "").trim();
    state.session.notes = note;
    state.sessions = state.sessions.map((item) => (
      item.id === state.session.id ? { ...item, notes: note || "No notes." } : item
    ));
    result = "Session note saved.";
  } else if (command.includes("record all") || command.includes("record everything")) {
    snapshotUndo("record all");
    result = recordAll();
  } else if (command.includes("play")) {
    snapshotUndo("play");
    state.transport = "Playing";
    result = "Playing session.";
  } else if (command.includes("stop")) {
    snapshotUndo("stop");
    state.transport = "Stopped";
    result = "Stopped.";
  } else if (command.includes("save this mix") || command.includes("save this setup") || command.includes("save setup")) {
    snapshotUndo("save mix");
    result = "Saved this musician's personal mix.";
  } else if (command.includes("save as preset")) {
    snapshotUndo("save preset");
    result = "Saved this musician's mix as a preset.";
  } else if (command.includes("recall previous mix")) {
    snapshotUndo("recall mix");
    result = "Previous personal mix recalled.";
  } else if (command.includes("reset my mix")) {
    snapshotUndo("reset mix");
    state.mix.masterMuted = false;
    state.mix.masterLevel = 72;
    state.channels.forEach((item) => {
      item.muted = false;
      item.solo = false;
      item.level = item.id === "drums" ? 64 : item.id === "bass" ? 57 : item.id === "guitar" ? 54 : item.id === "vocal" ? 61 : 50;
    });
    result = "Personal mix reset.";
  } else if (command.includes("new") && command.includes("track")) {
    snapshotUndo("new track request");
    result = requestNewTrack(command);
  } else if (command.includes("open sheets") || command.includes("show sheets") || command.includes("sheets")) {
    snapshotUndo("open sheets");
    state.mix.sheetsOpen = true;
    result = "Sheets opened.";
  } else if (command.includes("click")) {
    snapshotUndo("click");
    state.mix.clickOn = command.includes("off") ? false : command.includes("on") ? true : !state.mix.clickOn;
    result = `Click ${state.mix.clickOn ? "on" : "off"}.`;
  } else if (command.includes("master mute") || command.includes("mute master") || command.includes("unmute master")) {
    snapshotUndo("master mute");
    state.mix.masterMuted = !command.includes("unmute");
    result = `Master ${state.mix.masterMuted ? "muted" : "unmuted"}.`;
  } else if (command.includes("master") && command.includes("level")) {
    snapshotUndo("master level");
    const level = Number(command.match(/\d+/)?.[0] || state.mix.masterLevel);
    result = setMasterLevelExact(level);
  } else if (command.includes("venue console") || command.includes("house console")) {
    snapshotUndo("open venue console");
    result = openVenueConsole();
  } else if (command.includes("open console") || command.includes("my console") || command.includes("personal console")) {
    snapshotUndo("open personal console");
    result = openPersonalConsole();
  } else if (command.includes("console assist") || command.includes("listen") || command.includes("shape") || command.includes("target")) {
    snapshotUndo("console assist");
    result = updateAssist(command);
  } else if (command.includes("move") && command.includes("set")) {
    snapshotUndo("move to set");
    state.session.mixed = true;
    const set = {
      id: `set-${Date.now()}`,
      name: state.session.name,
      type: "Active",
      updated: "Now",
      songs: state.session.song ? [structuredClone(state.session.song)] : [],
      notes: "Built from the current session.",
    };
    state.activeSetId = set.id;
    state.sets.unshift(set);
    result = `${state.session.name} moved to set.`;
  } else if (command.includes("open drums") || command.includes("show drums") || command.includes("expand drums")) {
    snapshotUndo("open drums");
    state.channels.find((item) => item.id === "drums").expanded = true;
    result = "Drum channels are open.";
  } else if (command.includes("close drums") || command.includes("hide drums")) {
    snapshotUndo("close drums");
    state.channels.find((item) => item.id === "drums").expanded = false;
    result = "Drum channels are folded back to one fader.";
  } else {
    const item = resolveChannel(command);
    if (!item) {
      changed = false;
    } else if (command.includes("level")) {
      snapshotUndo("channel level");
      const level = Number(command.match(/\d+/)?.[0] || item.level);
      result = setChannelLevelExact(item, level);
    } else if (command.includes("mute") || command.includes("unmute")) {
      snapshotUndo("channel mute");
      item.muted = !command.includes("unmute");
      result = `${item.name} ${item.muted ? "muted" : "unmuted"}.`;
    } else if (command.includes("solo") || command.includes("unsolo")) {
      snapshotUndo("channel solo");
      item.solo = !command.includes("unsolo");
      result = `${item.name} ${item.solo ? "soloed" : "unsoloed"}.`;
    } else if (command.includes("louder") || command.includes("turn up") || command.includes("up") || command.includes("more")) {
      snapshotUndo("channel louder");
      result = setChannelLevel(item, 2);
    } else if (command.includes("quieter") || command.includes("turn down") || command.includes("down") || command.includes("less") || command.includes("lower")) {
      snapshotUndo("channel quieter");
      result = setChannelLevel(item, -2);
    } else if (command.includes("compress")) {
      snapshotUndo("compress channel");
      item.comp.enabled = true;
      item.comp.amount = command.includes("heavy") ? "heavy" : "medium";
      state.mix.assist.detail = `${item.name} compression adjusted inside this musician's Console mix.`;
      result = `Compression set on ${item.name} in this mix.`;
    } else if (command.includes("eq") || command.includes("bright") || command.includes("low end") || command.includes("mud")) {
      snapshotUndo("eq channel");
      item.eq.enabled = true;
      if (command.includes("bright")) item.eq.tone = "brighter";
      if (command.includes("low") || command.includes("mud")) item.eq.lowCut = true;
      state.mix.assist.detail = `${item.name} EQ adjusted inside this musician's Console mix.`;
      result = `EQ updated on ${item.name} in this mix.`;
    } else {
      changed = false;
    }
  }

  addLog(rawCommand, result);
  broadcast();
  return { result, changed };
}

function publicState() {
  return {
    transport: state.transport,
    venue: state.venue,
    mix: state.mix,
    session: state.session,
    activeSetId: state.activeSetId,
    activeSheetId: state.activeSheetId,
    sessions: state.sessions,
    channels: state.channels,
    sets: state.sets,
    sheets: state.sheets,
    log: state.log,
  };
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  res.end(body);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) {
        req.destroy();
        reject(new Error("Request body too large."));
      }
    });
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
  });
}

function broadcast() {
  const payload = `data: ${JSON.stringify(publicState())}\n\n`;
  for (const res of clients) res.write(payload);
}

function serveStatic(req, res) {
  const requested = new URL(req.url, `http://${req.headers.host}`).pathname;
  const filePath = path.normalize(path.join(ROOT, requested === "/" ? "index.html" : requested));
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.readFile(filePath, (error, data) => {
    if (error) {
      res.writeHead(404);
      res.end("Not found");
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    const types = {
      ".html": "text/html; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".json": "application/json; charset=utf-8",
    };
    res.writeHead(200, { "content-type": types[ext] || "application/octet-stream" });
    res.end(data);
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  try {
    if (req.method === "GET" && url.pathname === "/api/state") {
      sendJson(res, 200, publicState());
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/events") {
      res.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-store",
        connection: "keep-alive",
      });
      clients.add(res);
      res.write(`data: ${JSON.stringify(publicState())}\n\n`);
      req.on("close", () => clients.delete(res));
      return;
    }

    if (req.method === "POST" && url.pathname === "/api/command") {
      const body = await readJson(req);
      const outcome = runCommand(body.command);
      sendJson(res, 200, { ...outcome, state: publicState() });
      return;
    }

    serveStatic(req, res);
  } catch (error) {
    sendJson(res, 500, { error: error.message });
  }
});

server.listen(PORT, () => {
  console.log(`GIG listening at http://localhost:${PORT}`);
});
