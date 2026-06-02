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

const state = {
  transport: "Stopped",
  venue: {
    connected: true,
    rig: "Venue box",
    console: "Console ready on Venue",
    hardware: "Akai EIE USB attached",
    note: "Inputs are recognized and routed on Venue. This browser is the simple musician remote.",
  },
  session: {
    id: "session-1",
    name: "Untitled Session",
    mixed: false,
    takes: [
      { id: "take-1", name: "Scratch pass", status: "ready" },
    ],
  },
  channels: [
    { ...channel("drums", "Drums", "input 1-8", 64), type: "group", expanded: false, children: DRUM_CHILDREN },
    channel("bass", "Bass", "input-9", 57),
    channel("guitar", "Guitar", "input-10", 54),
    channel("vocal", "Vocal", "input-11", 61),
    channel("acoustic", "Acoustic", "input-12", 50),
    { ...channel("main", "Main", "main output", 46), type: "output" },
    { ...channel("phones", "Phones", "phones output", 62), type: "output" },
  ],
  sets: [],
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
    armed: id !== "main" && id !== "phones",
    eq: { enabled: false, tone: "flat", lowCut: false },
    comp: { enabled: false, amount: "off" },
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
    channels: structuredClone(state.channels),
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
  state.channels = previous.channels;
  state.sets = previous.sets;
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
  state.transport = "Stopped";
  state.session = {
    id: `session-${Date.now()}`,
    name,
    mixed: false,
    takes: [],
  };
  state.channels.forEach((item) => {
    item.muted = false;
    item.solo = false;
    item.armed = item.type !== "output";
    item.level = item.id === "main" ? 46 : item.id === "phones" ? 62 : item.level;
  });
  return `New session opened. Venue kept the recognized channels ready.`;
}

function openPreviousSession() {
  state.transport = "Stopped";
  state.session = {
    id: `session-${Date.now()}`,
    name: "Previous Session",
    mixed: false,
    takes: [
      { id: "take-prev-1", name: "Full band take 1", status: "ready" },
      { id: "take-prev-2", name: "Vocal fix", status: "ready" },
      { id: "take-prev-3", name: "Acoustic overdub", status: "ready" },
    ],
  };
  return "Previous session opened. The same Venue mix channels are ready.";
}

function recordAll() {
  const armed = allChannels().filter((item) => item.armed && item.type !== "output" && !item.children);
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
  } else if (command.includes("new session")) {
    snapshotUndo("new session");
    result = createSession();
  } else if (command.startsWith("name this session")) {
    snapshotUndo("name session");
    const name = rawCommand.replace(/name this session/i, "").trim() || "Untitled Session";
    state.session.name = name;
    result = `Session named ${name}.`;
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
    result = "Saved the current Venue mix for this session.";
  } else if (command.includes("move") && command.includes("set")) {
    snapshotUndo("move to set");
    state.session.mixed = true;
    state.sets.unshift({ id: `set-${Date.now()}`, name: state.session.name, takes: state.session.takes.length });
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
      result = `Compression set on ${item.name}.`;
    } else if (command.includes("eq") || command.includes("bright") || command.includes("low end") || command.includes("mud")) {
      snapshotUndo("eq channel");
      item.eq.enabled = true;
      if (command.includes("bright")) item.eq.tone = "brighter";
      if (command.includes("low") || command.includes("mud")) item.eq.lowCut = true;
      result = `EQ updated on ${item.name}.`;
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
    session: state.session,
    channels: state.channels,
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
  console.log(`GIG listening at http://localhost:${PORT}`);
});
