import fs from "node:fs/promises";
import path from "node:path";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = path.resolve("outputs/system-q-control-map-2026-05-07");
const outputPath = path.join(outputDir, "System_Q_Button_Control_Map_2026-05-07.xlsx");

const headers = [
  "ID",
  "Area",
  "Stage",
  "Visible Label",
  "Full Name / Meaning",
  "Control Type",
  "Click / Press Does",
  "Rotate / Twist Does",
  "Keyboard / SpaceMouse Behavior",
  "State Field(s)",
  "Range / Units",
  "Expected Visual Response",
  "Expected Audio / DSP Behavior",
  "Current Source Hook",
  "Proof Status",
  "Notes"
];

const stageDefs = [
  ["pre", "PRE", "Mic Pre", ["TBE", "LPF", "48V", "PHS", "HPF"]],
  ["harm", "HRM", "Harmonics", ["TBE", "H1", "H2", "H3", "H4", "H5"]],
  ["gate", "GTE", "Gate", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]],
  ["comp", "CMP", "Compressor", ["TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"]],
  ["eq", "EQ", "Equalizer", ["TBE", "FRQ", "GAN", "SHP", "BND", "TRN", "ATK", "SUT", "BD2"]],
  ["trn", "TRN", "Transient", ["FRQ", "ATK", "SUT", "DRV", "BND"]],
  ["xct", "XCT", "Exciter", ["FRQ", "ATK", "SUT", "DRV", "BND"]],
  ["tbe", "TBE", "Tube", ["DRV", "BND"]],
];

const stageEnable = {
  pre: "pre_enabled",
  harm: "harmonics_enabled",
  gate: "gate_enabled",
  comp: "comp_enabled",
  eq: "eq_enabled",
  trn: "trn_enabled",
  xct: "xct_enabled",
  tbe: "tbe_enabled",
};

const spec = {
  "pre:LPF": ["lpf_hz", "200 to 22000 Hz, log"],
  "pre:HPF": ["hpf_hz", "20 to 1500 Hz, log"],
  "harm:H1": ["harmonics[0]", "0.0 to 1.0"],
  "harm:H2": ["harmonics[1]", "0.0 to 1.0"],
  "harm:H3": ["harmonics[2]", "0.0 to 1.0"],
  "harm:H4": ["harmonics[3]", "0.0 to 1.0"],
  "harm:H5": ["harmonics[4]", "0.0 to 1.0"],
  "gate:THR": ["gate_threshold_db", "-60 to +12 dB"],
  "gate:RAT": ["gate_ratio", "1.0 to 20.0 ratio"],
  "gate:ATK": ["gate_attack_ms", "0.1 to 500 ms, log"],
  "gate:RLS": ["gate_release_ms", "10 to 2000 ms, log"],
  "gate:GAN": ["gate_makeup", "0.0 to 4.0 gain"],
  "gate:FRQ": ["gate_center_hz", "20 to 20000 Hz, log"],
  "gate:WDT": ["gate_width_oct", "0.1 to 6.0 octaves"],
  "comp:THR": ["comp_threshold_db", "-60 to +12 dB"],
  "comp:RAT": ["comp_ratio", "1.0 to 20.0 ratio"],
  "comp:ATK": ["comp_attack_ms", "0.1 to 500 ms, log"],
  "comp:RLS": ["comp_release_ms", "10 to 2000 ms, log"],
  "comp:GAN": ["comp_makeup", "0.0 to 4.0 gain"],
  "comp:FRQ": ["comp_center_hz", "20 to 20000 Hz, log"],
  "comp:WDT": ["comp_width_oct", "0.1 to 6.0 octaves"],
  "eq:FRQ": ["eq_freq", "20 to 22000 Hz, log"],
  "eq:GAN": ["eq_gain_db", "-24 to +24 dB"],
  "eq:BND": ["eq_width", "0.1 to 6.0 octaves"],
  "eq:TRN": ["trn_freq", "20 to 20000 Hz, log"],
  "eq:ATK": ["trn_attack", "-1.0 to +1.0"],
  "eq:SUT": ["trn_sustain", "-1.0 to +1.0"],
  "trn:FRQ": ["trn_freq", "20 to 20000 Hz, log"],
  "trn:ATK": ["trn_attack", "-1.0 to +1.0"],
  "trn:SUT": ["trn_sustain", "-1.0 to +1.0"],
  "trn:DRV": ["trn_drive", "0.0 to 1.0"],
  "xct:FRQ": ["xct_freq", "20 to 20000 Hz, log"],
  "xct:ATK": ["xct_attack", "-1.0 to +1.0"],
  "xct:SUT": ["xct_sustain", "-1.0 to +1.0"],
  "xct:DRV": ["xct_drive", "0.0 to 1.0"],
  "tbe:DRV": ["tbe_drive", "0.0 to 1.0"],
};

function pressState(stage, label) {
  if (label === "TBE") return stage === "pre" ? "tube" : `${stage}_tube`;
  if (label === "LPF") return "lpf_enabled";
  if (label === "HPF") return "hpf_enabled";
  if (label === "48V") return "phantom";
  if (label === "PHS") return "phase";
  if (label === "BND") return `${stage}_band_enabled`;
  if (label === "BD2") return "limit_band_enabled";
  const bypass = {
    gate: "gate_param_bypass[label]",
    comp: "comp_param_bypass[label]",
    eq: "eq_param_bypass[label]",
    harm: "harm_param_bypass[label]",
    trn: "tone_param_bypass[label]",
    xct: "tone_param_bypass[label]",
    tbe: "tone_param_bypass[label]",
  }[stage];
  return bypass || "";
}

function labelMeaning(stage, label) {
  const common = {
    TBE: "Tube coloration / tube stage toggle",
    LPF: "Low-pass filter",
    HPF: "High-pass filter",
    "48V": "Phantom power",
    PHS: "Phase invert",
    THR: "Threshold",
    RAT: "Ratio",
    ATK: "Attack",
    RLS: "Release",
    GAN: "Makeup gain",
    FRQ: "Frequency",
    WDT: "Width",
    SHP: "Shape",
    BND: "Band enable / band width control",
    TRN: "Transient frequency lane",
    SUT: "Sustain",
    DRV: "Drive",
    BD2: "Limiter band 2 enable",
  };
  if (stage === "harm" && /^H[1-5]$/.test(label)) return `Harmonic weight ${label.substring(1)}`;
  if (stage === "eq" && label === "BND") return "EQ band width";
  if (stage === "trn" && label === "BND") return "Transient band enable";
  if (stage === "xct" && label === "BND") return "Exciter band enable";
  if (stage === "tbe" && label === "BND") return "Tube band enable";
  return common[label] || label;
}

function pressDoes(stage, label) {
  const state = pressState(stage, label);
  if (label === "LPF" || label === "HPF") return `Toggles ${state}; frequency is changed by rotate/twist.`;
  if (label === "48V" || label === "PHS" || label === "TBE" || label === "BND" || label === "BD2") return `Toggles ${state}.`;
  return state ? `Toggles bypass state through ${state}; rotate/twist changes value when available.` : "No direct press action mapped.";
}

function rotateDoes(stage, label) {
  const s = spec[`${stage}:${label}`];
  if (!s) return "No rotate/twist adjustment mapped in current spec table.";
  return `Adjusts ${s[0]}. Log-scaled where marked; otherwise linear step.`;
}

function visual(stage, label) {
  if (label === "TBE" || label === "48V" || label === "PHS" || label === "BND" || label === "BD2") return "Cell value flips ON/off and active color changes.";
  if (spec[`${stage}:${label}`]) return "Cell numeric value changes; active/bypass coloring should update.";
  return "Header/cell focus ring and stage active color should update.";
}

function dsp(stage, label) {
  if (stage === "pre") return "Affects channel input/pre processing when pre stage and matching toggle are active.";
  if (stage === "harm") return "Affects harmonic processing when harmonics are enabled and parameter is not bypassed.";
  if (stage === "gate") return "Affects gate processing when gate or gate band is enabled.";
  if (stage === "comp") return "Affects compressor processing when compressor or compressor band is enabled.";
  if (stage === "eq") return "Affects EQ/transient/limiter-related processing when EQ path is enabled and not bypassed.";
  if (stage === "trn") return "Affects transient processor when TRN stage is enabled.";
  if (stage === "xct") return "Affects exciter processor when XCT stage is enabled.";
  if (stage === "tbe") return "Affects tube/drive processor when TBE stage is enabled.";
  return "";
}

const rows = [];

for (const [stage, header, stageName, params] of stageDefs) {
  rows.push([
    `editor-${stage}-header`,
    "Editor Grid",
    stageName,
    header,
    `${stageName} stage header`,
    "Stage header button",
    `Toggles stage enable field ${stageEnable[stage]}.`,
    "No rotate/twist adjustment mapped while header has focus.",
    "Arrow keys move focus. Space/Enter press. Down enters first param row.",
    stageEnable[stage],
    "Boolean",
    "Stage header active color and selected stage focus should update.",
    dsp(stage, "HEADER"),
    "system_q_ui.py:63 _STAGE_GRID; :768 _press_unified_editor_cell",
    "Mapped from source, not OS-click proven",
    ""
  ]);
  for (const label of params) {
    const s = spec[`${stage}:${label}`];
    rows.push([
      `editor-${stage}-${label.toLowerCase()}`,
      "Editor Grid",
      stageName,
      label,
      labelMeaning(stage, label),
      s ? "Parameter cell button + rotatable value" : "Toggle/bypass cell button",
      pressDoes(stage, label),
      rotateDoes(stage, label),
      "Click selects and presses. Space/Enter presses focused cell. '[' and ']' rotate by -0.5/+0.5. SpaceMouse twist rotates in editor scope.",
      [pressState(stage, label), s?.[0]].filter(Boolean).join("; "),
      s ? s[1] : "Boolean / bypass",
      visual(stage, label),
      dsp(stage, label),
      "system_q_ui.py:63 _STAGE_GRID; :768 _press_unified_editor_cell; :805 _adjust_unified_editor_cell; :880 _stage_cell_value",
      "Mapped from source, not OS-click proven",
      stage === "eq" && ["TRN", "ATK", "SUT"].includes(label) ? "EQ column edits transient state fields in current code." :
        ["trn", "xct", "tbe"].includes(stage) && !["BND"].includes(label) ? "Press bypass uses shared tone_param_bypass labels, so labels overlap between TRN/XCT/TBE." : ""
    ]);
  }
}

const transport = [
  ["play", "PLY", "Play", "Toggles playback through engine.toggle_play().", "Transport focus only; no current rotate handler in source.", "engine.playing", "Boolean", "Play button changes armed/playing color.", "Starts/stops stream playback."],
  ["stop", "STP", "Stop", "Stops playback and resets channel positions through engine.stop().", "Transport focus only; no current rotate handler in source.", "engine.playing; channel.position", "Boolean / sample position", "Stop button receives focus flash.", "Stops stream and rewinds to start."],
  ["rewind", "REW", "Rewind", "Rewinds channel positions through engine.rewind().", "Transport focus only; no current rotate handler in source.", "channel.position", "Sample position", "Rewind button receives focus flash.", "Sets playhead to start."],
  ["forward", "FFD", "Fast forward", "Jumps forward about 5 seconds through engine.jump_forward().", "Transport focus only; no current rotate handler in source.", "channel.position", "Sample position", "Forward button receives focus flash.", "Moves playhead forward."],
  ["record", "REC", "Record arm", "Toggles current channel record_armed if current channel is not master.", "Transport focus only; no current rotate handler in source.", "record_armed", "Boolean", "Record button changes armed color when active.", "Record-to-disk is not implemented here; this is arm state only."],
  ["oscillator", "OSC", "Oscillator monitor", "Toggles engine.generator_mode between osc and none.", "Transport focus only; no current rotate handler in source.", "generator_mode", "none/osc", "Generator button active color should update.", "Sine oscillator is synthesized when generator mode is active."],
  ["pink", "PNK", "Pink noise", "Toggles engine.generator_mode between pink and none.", "Transport focus only; no current rotate handler in source.", "generator_mode", "none/pink", "Generator button active color should update.", "Pink noise is synthesized when generator mode is active."],
  ["white", "WHT", "White noise", "Toggles engine.generator_mode between white and none.", "Transport focus only; no current rotate handler in source.", "generator_mode", "none/white", "Generator button active color should update.", "White noise is synthesized when generator mode is active."],
  ["pink_pulse", "PLS", "Pink pulse", "Toggles engine.generator_mode between pink_pulse and none.", "Transport focus only; no current rotate handler in source.", "generator_mode", "none/pink_pulse", "Generator button active color should update.", "Pulsed pink noise is synthesized when generator mode is active."],
  ["white_hot", "HOT", "White hot", "Toggles engine.generator_mode between white_hot and none.", "Transport focus only; no current rotate handler in source.", "generator_mode", "none/white_hot", "Generator button active color should update.", "Hotter white noise is synthesized when generator mode is active."],
];

for (const [id, label, name, click, rotate, state, range, visualText, dspText] of transport) {
  rows.push([
    `transport-${id}`,
    "Transport Panel",
    "Transport",
    label,
    name,
    "Clickable label button",
    click,
    rotate,
    "Arrow keys move 2x5 transport focus. Space/Enter invokes focused transport button. Escape/back exits transport to console footer.",
    state,
    range,
    visualText,
    dspText,
    "system_q_ui.py:79 _TRANSPORT_BUTTONS; :181-199 _tx_*; :673 _on_transport_click; system_q_dsp.py:90-103 transport engine methods",
    "Mapped from source, not OS-click proven",
    ""
  ]);
}

const inputRows = [
  ["keyboard-left", "Keyboard", "Navigation", "Left Arrow", "Move focus left", "Key", "Moves focus left in current nav scope.", "None", "Console: previous stage/channel. Editor: previous header/param. Transport: previous button.", "nav_scope plus selected focus fields", "Discrete", "Focus ring moves left.", "No direct DSP change unless focus move precedes a press.", "system_q_ui.py:174 _bind_nav_keys; :614 _handle_nav", "Mapped from source, not OS-key proven", ""],
  ["keyboard-right", "Keyboard", "Navigation", "Right Arrow", "Move focus right", "Key", "Moves focus right in current nav scope.", "None", "Console: next stage/channel. Editor: next header/param. Transport: next button.", "nav_scope plus selected focus fields", "Discrete", "Focus ring moves right.", "No direct DSP change unless focus move precedes a press.", "system_q_ui.py:174 _bind_nav_keys; :614 _handle_nav", "Mapped from source, not OS-key proven", ""],
  ["keyboard-up", "Keyboard", "Navigation", "Up Arrow", "Move focus up", "Key", "Moves focus up in current nav scope.", "None", "Editor param row returns to header. Transport top row returns to editor.", "nav_scope plus selected focus fields", "Discrete", "Focus ring moves up.", "No direct DSP change unless focus move precedes a press.", "system_q_ui.py:174 _bind_nav_keys; :614 _handle_nav", "Mapped from source, not OS-key proven", ""],
  ["keyboard-down", "Keyboard", "Navigation", "Down Arrow", "Move focus down", "Key", "Moves focus down in current nav scope.", "None", "Editor header enters param row; editor param down enters transport.", "nav_scope plus selected focus fields", "Discrete", "Focus ring moves down.", "No direct DSP change unless focus move precedes a press.", "system_q_ui.py:174 _bind_nav_keys; :614 _handle_nav", "Mapped from source, not OS-key proven", ""],
  ["keyboard-space-enter", "Keyboard", "Navigation", "Space / Enter", "Press focused control", "Key", "Invokes current focused editor/transport/console press action.", "None", "Same press path as clicked cell/button when focus is correct.", "Depends on focused control", "Action", "Focused control flashes or changes active color.", "Depends on focused control.", "system_q_ui.py:178-179 _bind_nav_keys; :614 _handle_nav", "Mapped from source, not OS-key proven", ""],
  ["keyboard-brackets", "Keyboard", "Rotate", "[ / ]", "Decrease/increase focused editor value", "Keys", "None", "Calls _adjust_unified_editor_cell(-0.5/+0.5).", "Only adjusts editor param cells that exist in spec table.", "Current focused spec field", "Analog step", "Numeric cell value should update.", "Parameter changes should affect DSP if stage is active and not bypassed.", "system_q_ui.py:180-181 _bind_nav_keys; :805 _adjust_unified_editor_cell", "Mapped from source, not OS-key proven", ""],
  ["spacemouse-twist", "SpaceMouse", "Rotate", "Twist", "Analog twist", "Hardware axis", "None by itself.", "Editor scope: adjusts focused parameter. Console scope: pages selected channel.", "Press button 0 maps to press; cardinal directions map to nav.", "Focused param or selected_channel", "Analog axis", "Numeric cell or selected channel should change.", "Parameter changes should affect DSP if active.", "system_q_ui.py:579 _poll_spacemouse", "Mapped from source, not hardware proven", ""],
  ["strip-click", "Mixer Strip", "Console", "Strip body", "Select channel strip", "Canvas click region", "Selects strip/channel and puts nav_scope in console.", "Console SpaceMouse twist pages selected channel.", "After selection, stage row/footers are navigable.", "selected_channel; nav_scope", "Channel index", "Selected strip highlight changes.", "No direct DSP change.", "system_q_ui.py:662 _on_strip_click", "Mapped from source, not OS-click proven", "Current click handler selects channel only; it does not directly open stage capsules."],
  ["console-stage-press", "Mixer Strip", "Console", "Stage row", "Open selected stage editor", "Focused console press", "Press opens editor for selected channel/stage.", "Console twist changes selected channel.", "Arrow left/right changes selected stage; up/down changes console row.", "selected_stage_key; editor_channel; nav_scope", "Discrete", "Editor title/stage focus should update.", "No direct DSP change until editor controls are pressed/rotated.", "system_q_ui.py:625 _handle_console_nav; :702 _open_stage_editor", "Mapped from source, not OS-click proven", ""],
  ["footer-press", "Mixer Strip", "Console", "Footer row", "Enter transport focus", "Focused console press", "Press footer row enters transport focus.", "None", "Transport focus starts after footer press.", "nav_scope", "Discrete", "Transport focus ring appears.", "No direct DSP change.", "system_q_ui.py:639 _handle_console_nav", "Mapped from source, not OS-click proven", "Footer solo/mute visible cells are drawn, but current source press path enters transport rather than toggling S/M."],
];
rows.push(...inputRows);

const staleRows = [
  ["SHT", "Transport panel", "Old TSV lists shuttle mode. Not present in current _TRANSPORT_BUTTONS.", "Needs decision: restore button or remove from spec."],
  ["SRB", "Transport panel", "Old TSV lists scrub mode. Not present in current _TRANSPORT_BUTTONS.", "Needs decision: restore button or remove from spec."],
  ["RDE", "Transport panel", "Old TSV lists automation READ stub. Not present in current _TRANSPORT_BUTTONS.", "Needs decision: restore button or remove from spec."],
  ["WRT", "Transport panel", "Old TSV lists automation WRITE stub. Not present in current _TRANSPORT_BUTTONS.", "Needs decision: restore button or remove from spec."],
  ["TRM", "Transport panel", "Old TSV lists automation TRIM stub. Not present in current _TRANSPORT_BUTTONS.", "Needs decision: restore button or remove from spec."],
  ["LTC", "Transport panel", "Old TSV lists automation LATCH stub. Not present in current _TRANSPORT_BUTTONS.", "Needs decision: restore button or remove from spec."],
  ["UNDO", "Transport panel", "Old TSV lists undo stub. Not present in current _TRANSPORT_BUTTONS.", "Needs command-history decision."],
  ["REDO", "Transport panel", "Old TSV lists redo stub. Not present in current _TRANSPORT_BUTTONS.", "Needs command-history decision."],
  ["HRM GAN", "Editor grid", "Adjust spec has harm:GAN but HRM column does not currently include GAN.", "Likely stale/planned control; not visible in current grid."],
  ["EQ SHP rotate", "Editor grid", "SHP is visible and press toggles bypass, but no rotate spec currently maps EQ shape/type.", "If SHP should rotate EQ type, implementation is missing."],
  ["Footer S/M click", "Mixer strip", "S and M footer cells are drawn, but current press path enters transport and click path selects strip.", "If visible solo/mute buttons must click, current handler is incomplete."],
];

const wb = Workbook.create();
let ws = wb.worksheets.add("Control Map");
ws.showGridLines = false;
ws.getRangeByIndexes(0, 0, rows.length + 1, headers.length).values = [headers, ...rows];
ws.freezePanes.freezeRows(1);
ws.freezePanes.freezeColumns(4);
ws.tables.add(`A1:P${rows.length + 1}`, true, "ControlMap");
ws.getRange("A1:P1").format.fill = "#1F4E78";
ws.getRange("A1:P1").format.font = { color: "#FFFFFF", bold: true };
ws.getRange("A:P").format.wrapText = true;
const widths = [180, 120, 120, 90, 220, 160, 280, 260, 300, 220, 150, 240, 260, 300, 170, 280];
widths.forEach((w, i) => ws.getRangeByIndexes(0, i, rows.length + 1, 1).format.columnWidthPx = w);
ws.getRangeByIndexes(1, 0, rows.length, headers.length).format.rowHeightPx = 54;

const summary = wb.worksheets.add("Stage Summary");
summary.showGridLines = false;
const stageSummary = [
  ["Stage / Area", "Visible Controls", "Press Behavior", "Rotate Behavior", "Primary State Fields", "Current Caveat"],
  ...stageDefs.map(([stage, header, name, params]) => [
    `${header} - ${name}`,
    `${1 + params.length} controls (${header} header + ${params.length} cells)`,
    `Header toggles ${stageEnable[stage]}; cells toggle direct state or bypass.`,
    `${params.filter((p) => spec[`${stage}:${p}`]).length} rotatable cell(s) mapped.`,
    [stageEnable[stage], ...params.map((p) => pressState(stage, p)).filter(Boolean)].join("; "),
    stage === "eq" ? "SHP has press/bypass mapping but no rotate/type mapping." :
      ["trn", "xct", "tbe"].includes(stage) ? "Tone bypass dict is shared across these stage labels." : ""
  ]),
  ["Transport Panel", `${transport.length} controls`, "Click/press invokes _tx_* handlers.", "No current transport rotate handler found.", "engine.playing; channel.position; record_armed; generator_mode", "Old TSV listed SHT/SRB/etc., but current source does not."],
  ["Keyboard / SpaceMouse", `${inputRows.length} input/navigation rows`, "Navigation and press dispatch through _handle_nav.", "Brackets and SpaceMouse twist adjust mapped editor values.", "nav_scope and focused state fields", "Hardware/OS proof still required."],
];
summary.getRangeByIndexes(0, 0, stageSummary.length, 6).values = stageSummary;
summary.freezePanes.freezeRows(1);
summary.tables.add(`A1:F${stageSummary.length}`, true, "StageSummary");
summary.getRange("A1:F1").format.fill = "#385723";
summary.getRange("A1:F1").format.font = { color: "#FFFFFF", bold: true };
summary.getRange("A:F").format.wrapText = true;
[180, 140, 260, 240, 320, 280].forEach((w, i) => summary.getRangeByIndexes(0, i, stageSummary.length, 1).format.columnWidthPx = w);
summary.getRangeByIndexes(1, 0, stageSummary.length - 1, 6).format.rowHeightPx = 54;

const legend = wb.worksheets.add("Interaction Legend");
legend.showGridLines = false;
const legendRows = [
  ["Term", "Meaning in this workbook"],
  ["Click", "Physical mouse click on a visible label/cell/button."],
  ["Press", "Keyboard Space/Enter or SpaceMouse button action against the currently focused control."],
  ["Rotate / Twist", "Analog parameter adjustment through SpaceMouse twist or keyboard bracket keys where current source maps a spec entry."],
  ["Mapped from source", "The behavior is derived from current Python source and existing control TSV/context. It is not a claim that OS-level clicking has passed."],
  ["OS-click proven", "Would require a real running UI pass that clicks each visible control and captures before/after state/screenshot evidence."],
  ["Stale / missing", "A control exists in older context/TSV or adjust spec but is not present as a visible current UI control."],
];
legend.getRangeByIndexes(0, 0, legendRows.length, 2).values = legendRows;
legend.tables.add(`A1:B${legendRows.length}`, true, "InteractionLegend");
legend.getRange("A1:B1").format.fill = "#7030A0";
legend.getRange("A1:B1").format.font = { color: "#FFFFFF", bold: true };
legend.getRange("A:B").format.wrapText = true;
legend.getRange("A:A").format.columnWidthPx = 170;
legend.getRange("B:B").format.columnWidthPx = 620;
legend.getRangeByIndexes(1, 0, legendRows.length - 1, 2).format.rowHeightPx = 44;

const stale = wb.worksheets.add("Stale Or Missing");
stale.showGridLines = false;
stale.getRangeByIndexes(0, 0, staleRows.length + 1, 4).values = [["Label", "Area", "Finding", "Required Decision"], ...staleRows];
stale.freezePanes.freezeRows(1);
stale.tables.add(`A1:D${staleRows.length + 1}`, true, "StaleOrMissing");
stale.getRange("A1:D1").format.fill = "#7F1D1D";
stale.getRange("A1:D1").format.font = { color: "#FFFFFF", bold: true };
stale.getRange("A:D").format.wrapText = true;
[120, 150, 430, 330].forEach((w, i) => stale.getRangeByIndexes(0, i, staleRows.length + 1, 1).format.columnWidthPx = w);
stale.getRangeByIndexes(1, 0, staleRows.length, 4).format.rowHeightPx = 52;

const sources = wb.worksheets.add("Sources");
sources.showGridLines = false;
const sourceRows = [
  ["Source", "What it provided"],
  ["Development/software/system_q_ui.py", "_STAGE_GRID, _TRANSPORT_BUTTONS, click handlers, keyboard bindings, press mapping, rotate spec, cell value display."],
  ["Development/software/system_q_core.py", "ChannelState fields and defaults."],
  ["Development/software/system_q_dsp.py", "Transport engine methods and generator synthesis modes."],
  ["Development/software/system_q_console_controls.tsv", "Older intended control notes; used only to identify stale/missing controls where it disagrees with current source."],
  ["Context/Project/Project_Context.html and Context/Daily/2026-05-07.html", "Project rule that real verification must prove controls through UI behavior, not claims."],
];
sources.getRangeByIndexes(0, 0, sourceRows.length, 2).values = sourceRows;
sources.tables.add(`A1:B${sourceRows.length}`, true, "Sources");
sources.getRange("A1:B1").format.fill = "#404040";
sources.getRange("A1:B1").format.font = { color: "#FFFFFF", bold: true };
sources.getRange("A:B").format.wrapText = true;
sources.getRange("A:A").format.columnWidthPx = 360;
sources.getRange("B:B").format.columnWidthPx = 660;
sources.getRangeByIndexes(1, 0, sourceRows.length - 1, 2).format.rowHeightPx = 48;

for (const sheetName of ["Control Map", "Stage Summary", "Interaction Legend", "Stale Or Missing", "Sources"]) {
  const sheet = wb.worksheets.getItem(sheetName);
  sheet.getUsedRange().format.font = { name: "Aptos", size: 10 };
  sheet.getUsedRange().format.verticalAlignment = "top";
}

const inspect = await wb.inspect({
  kind: "table",
  range: "Control Map!A1:P18",
  include: "values,formulas",
  tableMaxRows: 18,
  tableMaxCols: 16,
});
console.log(inspect.ndjson);

const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await wb.render({ sheetName: "Control Map", range: "A1:P22", scale: 1, format: "png" });
await wb.render({ sheetName: "Stage Summary", range: "A1:F14", scale: 1, format: "png" });
await wb.render({ sheetName: "Interaction Legend", range: "A1:B8", scale: 1, format: "png" });
await wb.render({ sheetName: "Stale Or Missing", range: "A1:D13", scale: 1, format: "png" });
await wb.render({ sheetName: "Sources", range: "A1:B6", scale: 1, format: "png" });

await fs.mkdir(outputDir, { recursive: true });
const blob = await SpreadsheetFile.exportXlsx(wb);
await blob.save(outputPath);
console.log(outputPath);
