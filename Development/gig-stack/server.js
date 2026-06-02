const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const PORT = Number(process.env.PORT || 4180);
const ROOT = __dirname;

const state = {
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
      makeTrack("track-1", "Vocal", "input-1", "ready"),
    ],
  },
  sets: [],
  log: [],
  undoStack: [],
};

const clients = new Set();

function makeTrack(id, name, inputId, status = "ready", note = "") {
  return {
    id,
    name,
    inputId,
    status,
    note,
    level: 60,
    muted: false,
    solo: false,
    armed: false,
    takes: 0,
    eq: { enabled: false, tone: "flat", lowCut: false },
    comp: { enabled: false, amount: "off" },
    reverb: { enabled: false, amount: "dry" },
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
    session: structuredClone(state.session),
    sets: structuredClone(state.sets),
  });
  state.undoStack = state.undoStack.slice(-16);
}

function undoLast() {
  const previous = state.undoStack.pop();
  if (!previous) return "Nothing to undo.";
  state.transport = previous.transport;
  state.venue = previous.venue;
  state.session = previous.session;
  state.sets = previous.sets;
  return `Undone: ${previous.label}.`;
}

function selectedTrack() {
  return state.session.tracks.find((track) => track.id === state.session.selectedTrackId) || state.session.tracks[0] || null;
}

function wordToNumber(value) {
  const words = { one: 1, two: 2, three: 3, four: 4 };
  return words[value] || Number(value);
}

function resolveInput(command) {
  const match = command.match(/\binput[-\s]*(1|2|3|4|one|two|three|four)\b/);
  if (!match) return null;
  const number = wordToNumber(match[1]);
  return state.venue.inputs.find((input) => input.id === `input-${number}`) || null;
}

function resolveTrack(command) {
  const current = selectedTrack();
  if (command.includes("this track") || command.includes("selected track") || command.includes(" it") || command.includes("this ")) {
    return current;
  }
  const byName = state.session.tracks.find((track) => command.includes(track.name.toLowerCase()));
  return byName || current;
}

function createSession(name = "Untitled Session") {
  state.session = {
    id: `session-${Date.now()}`,
    name,
    mixed: false,
    selectedTrackId: "",
    tracks: [],
  };
  return `New session opened: ${state.session.name}.`;
}

function addTrack(name = "Track", inputId = "input-1", status = "ready", note = "") {
  const id = `track-${Date.now()}-${state.session.tracks.length + 1}`;
  const track = makeTrack(id, name, inputId, status, note);
  state.session.tracks.push(track);
  state.session.selectedTrackId = id;
  return status === "waiting"
    ? `${name} track created and waiting for an input.`
    : `${name} track created on ${inputId}.`;
}

function openPreviousSession() {
  state.session = {
    id: `session-${Date.now()}`,
    name: "Previous Session",
    mixed: false,
    selectedTrackId: "track-prev-1",
    tracks: [
      makeTrack("track-prev-1", "Drums", "input-1", "ready", "Submixed drums on the current four-input rig."),
      makeTrack("track-prev-2", "Bass", "input-2"),
      makeTrack("track-prev-3", "Guitar", "input-3"),
      makeTrack("track-prev-4", "Vocal", "input-4"),
      makeTrack("track-prev-5", "Acoustic Guitar", "waiting", "waiting", "Needs another input or an overdub pass on the Akai EIE."),
    ],
  };
  return "Previous session opened with the saved band tracks.";
}

function setupBandTracks() {
  state.session.tracks = [
    makeTrack(`track-${Date.now()}-drums`, "Drums", "input-1", "ready", "Submixed drums on Akai input 1."),
    makeTrack(`track-${Date.now()}-bass`, "Bass", "input-2"),
    makeTrack(`track-${Date.now()}-guitar`, "Guitar", "input-3"),
    makeTrack(`track-${Date.now()}-vocal`, "Vocal", "input-4"),
    makeTrack(
      `track-${Date.now()}-acoustic`,
      "Acoustic Guitar",
      "waiting",
      "waiting",
      "Akai EIE has four inputs. Plug acoustic into an open input later or overdub it after the first pass.",
    ),
  ];
  state.session.selectedTrackId = state.session.tracks[0].id;
  return "Band tracks are ready: drums, bass, guitar, and vocal are on inputs 1-4; acoustic guitar is waiting for an input or overdub.";
}

function recordAllReadyTracks() {
  const ready = state.session.tracks.filter((track) => track.status !== "waiting" && track.inputId !== "waiting");
  for (const track of ready) {
    track.armed = true;
    track.takes += 1;
  }
  state.transport = "Recording";
  const waiting = state.session.tracks.filter((track) => track.status === "waiting").map((track) => track.name);
  return waiting.length
    ? `Recording ${ready.length} ready tracks. ${waiting.join(", ")} is waiting for an input or overdub.`
    : `Recording all ${ready.length} tracks.`;
}

function setInputLevel(input, amount) {
  input.level = clamp(input.level + amount);
  return `${input.label} is ${amount > 0 ? "up" : "down"} ${Math.abs(amount)} points.`;
}

function setTrackLevel(track, amount) {
  track.level = clamp(track.level + amount);
  return `${track.name} is ${amount > 0 ? "up" : "down"} ${Math.abs(amount)} points.`;
}

function runCommand(rawCommand) {
  const command = String(rawCommand || "").trim().toLowerCase();
  if (!command) return { result: "No command.", changed: false };

  let result = "Command not recognized yet.";
  let changed = true;

  if (command === "undo" || command.includes("undo")) {
    changed = false;
    result = undoLast();
  } else if (command.includes("open previous")) {
    snapshotUndo("open previous session");
    result = openPreviousSession();
  } else if (command.includes("new session")) {
    snapshotUndo("new session");
    result = createSession();
  } else if (command.includes("recognize") && command.includes("input")) {
    changed = false;
    result = "Venue recognizes Akai EIE inputs input-1 through input-4, plus phones and main outputs.";
  } else if (command.startsWith("name this session")) {
    snapshotUndo("name session");
    const name = rawCommand.replace(/name this session/i, "").trim() || "Untitled Session";
    state.session.name = name;
    result = `Session named ${name}.`;
  } else if (command.includes("start akai") || command.includes("start eie")) {
    snapshotUndo("start akai");
    state.venue.connected = true;
    result = "Venue is ready with Akai EIE USB: input-1 through input-4, phones, and main.";
  } else if (command.includes("save this setup") || command.includes("save setup")) {
    snapshotUndo("save setup");
    state.venue.setupName = `Akai EIE setup ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
    result = `Saved setup: ${state.venue.setupName}.`;
  } else if (
    command.includes("setup band") ||
    command.includes("set up band") ||
    command.includes("band tracks") ||
    command.includes("drums bass guitar vocal") ||
    command.includes("drums, bass, guitar")
  ) {
    snapshotUndo("setup band tracks");
    result = setupBandTracks();
  } else if (command.includes("create") || command.includes("add track") || command.includes("new track")) {
    snapshotUndo("add track");
    const input = resolveInput(command) || state.venue.inputs[0];
    let name = "Track";
    if (command.includes("acoustic")) name = "Acoustic Guitar";
    else if (command.includes("vocal")) name = "Vocal";
    else if (command.includes("guitar")) name = "Guitar";
    else if (command.includes("bass")) name = "Bass";
    else if (command.includes("drum")) name = "Drums";
    else if (command.includes("keys")) name = "Keys";
    result = addTrack(name, input.id);
  } else if (command.startsWith("select track-")) {
    snapshotUndo("select track");
    const id = command.replace("select ", "").trim();
    if (state.session.tracks.some((track) => track.id === id)) {
      state.session.selectedTrackId = id;
      result = `Selected ${selectedTrack().name}.`;
    } else {
      changed = false;
      result = "Track not found.";
    }
  } else if (command.includes("record all")) {
    snapshotUndo("record all tracks");
    result = recordAllReadyTracks();
  } else if (command.includes("record")) {
    snapshotUndo("record track");
    const track = resolveTrack(command);
    if (track) {
      if (track.status === "waiting" || track.inputId === "waiting") {
        changed = false;
        result = `${track.name} is waiting for an input before recording.`;
      } else {
      track.armed = true;
      track.takes += 1;
      state.transport = "Recording";
      result = `Recording ${track.name}, take ${track.takes}.`;
      }
    }
  } else if (command.includes("play")) {
    snapshotUndo("play");
    state.transport = "Playing";
    result = "Playing session.";
  } else if (command.includes("stop")) {
    snapshotUndo("stop");
    state.transport = "Stopped";
    result = "Stopped.";
  } else if (resolveInput(command) && (command.includes("mute") || command.includes("unmute"))) {
    snapshotUndo("input mute");
    const input = resolveInput(command);
    input.muted = !command.includes("unmute");
    result = `${input.label} ${input.muted ? "muted" : "unmuted"}.`;
  } else if (resolveInput(command) && (command.includes("louder") || command.includes("up") || command.includes("more"))) {
    snapshotUndo("input louder");
    result = setInputLevel(resolveInput(command), 2);
  } else if (resolveInput(command) && (command.includes("quieter") || command.includes("down") || command.includes("less") || command.includes("lower"))) {
    snapshotUndo("input quieter");
    result = setInputLevel(resolveInput(command), -2);
  } else if (command.includes("set this track level")) {
    snapshotUndo("track level");
    const track = selectedTrack();
    const level = Number(command.match(/\d+/)?.[0] || track.level);
    track.level = clamp(level);
    result = `${track.name} level set to ${track.level}.`;
  } else if (command.includes("mute this track") || command.includes("mute track")) {
    snapshotUndo("mute track");
    const track = resolveTrack(command);
    track.muted = true;
    result = `${track.name} muted.`;
  } else if (command.includes("unmute this track") || command.includes("unmute track")) {
    snapshotUndo("unmute track");
    const track = resolveTrack(command);
    track.muted = false;
    result = `${track.name} unmuted.`;
  } else if (command.includes("solo")) {
    snapshotUndo("solo track");
    const track = resolveTrack(command);
    track.solo = !command.includes("unsolo");
    result = `${track.name} ${track.solo ? "soloed" : "unsoloed"}.`;
  } else if (command.includes("arm")) {
    snapshotUndo("arm track");
    const track = resolveTrack(command);
    track.armed = !track.armed;
    result = `${track.name} ${track.armed ? "armed" : "disarmed"}.`;
  } else if (command.includes("louder") || command.includes("turn this up") || command.includes("make this up")) {
    snapshotUndo("track louder");
    result = setTrackLevel(resolveTrack(command), 2);
  } else if (command.includes("quieter") || command.includes("turn this down") || command.includes("make this down")) {
    snapshotUndo("track quieter");
    result = setTrackLevel(resolveTrack(command), -2);
  } else if (command.includes("eq") || command.includes("brighter") || command.includes("low end") || command.includes("mud")) {
    snapshotUndo("eq track");
    const track = resolveTrack(command);
    track.eq.enabled = true;
    if (command.includes("bright")) track.eq.tone = "brighter";
    if (command.includes("mud") || command.includes("low end") || command.includes("low cut")) track.eq.lowCut = true;
    result = `EQ updated on ${track.name}.`;
  } else if (command.includes("compress")) {
    snapshotUndo("compress track");
    const track = resolveTrack(command);
    track.comp.enabled = true;
    track.comp.amount = command.includes("heavy") ? "heavy" : "medium";
    result = `Compression set on ${track.name}.`;
  } else if (command.includes("reverb")) {
    snapshotUndo("reverb track");
    const track = resolveTrack(command);
    track.reverb.enabled = true;
    track.reverb.amount = command.includes("little") ? "small" : "room";
    result = `Reverb added to ${track.name}.`;
  } else if (command.includes("move") && command.includes("set")) {
    snapshotUndo("move to set");
    state.session.mixed = true;
    const setName = state.session.name.replace(/session/i, "Set");
    state.sets.unshift({ id: `set-${Date.now()}`, name: setName, tracks: state.session.tracks.length });
    result = `${state.session.name} moved to set.`;
  } else {
    changed = false;
  }

  addLog(rawCommand, result);
  broadcast();
  return { result, changed };
}

function publicState() {
  return {
    transport: state.transport,
    venue: state.venue,
    session: state.session,
    sets: state.sets,
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
  console.log(`GIG Stack listening at http://localhost:${PORT}`);
});
