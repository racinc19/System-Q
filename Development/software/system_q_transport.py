from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransportButton:
    row: int
    col: int
    key: str
    label: str
    color: str
    glyph: str

    def grid_row(self) -> tuple[int, int, str, str, str, str]:
        return (self.row, self.col, self.key, self.label, self.color, self.glyph)


TRANSPORT_ROWS = 2
TRANSPORT_COLS = 13

TRANSPORT_BUTTONS: tuple[TransportButton, ...] = (
    TransportButton(0, 0, "play_stop", "PLY/SPT", "#6ff0c1", "▶"),
    TransportButton(0, 1, "advance", "ADV", "#89a0b6", "↔"),
    TransportButton(0, 2, "record", "REC", "#ff3b30", "●"),
    TransportButton(0, 3, "cycle", "CYC", "#fbbf24", "↻"),
    TransportButton(0, 4, "prepost", "PRE/POST", "#e5e7eb", "⏱"),
    TransportButton(0, 6, "channel_solo", "SOL", "#ffd166", "S"),
    TransportButton(0, 7, "channel_mute", "MTE", "#ff6a53", "M"),
    TransportButton(0, 8, "channel_arm", "REC", "#ff8fa3", "●"),
    TransportButton(0, 9, "channel_pan", "PAN", "#75baff", "◉"),
    TransportButton(0, 12, "oscillator", "OSC", "#fbbf24", "∿"),
    TransportButton(1, 0, "undo", "UND", "#e5e7eb", "↶"),
    TransportButton(1, 1, "cut", "CUT", "#fb7185", "✂"),
    TransportButton(1, 2, "paste", "PST", "#86efac", "▣"),
    TransportButton(1, 3, "copy", "CPY", "#93c5fd", "⧉"),
    TransportButton(1, 4, "cancel_edit", "CNL", "#fca5a5", "×"),
    TransportButton(1, 5, "zoom", "ZM", "#fcd34d", "⌕"),
    TransportButton(1, 6, "shuttle_scrub", "SRB", "#9ca3af", "»"),
    TransportButton(1, 8, "auto_read", "RED", "#7dd3fc", "R"),
    TransportButton(1, 9, "auto_write", "WRT", "#f87171", "W"),
    TransportButton(1, 10, "auto_trim", "TRM", "#fbbf24", "T"),
    TransportButton(1, 11, "auto_latch", "LTC", "#c084fc", "L"),
)

TRANSPORT_BUTTON_GRID: tuple[tuple[int, int, str, str, str, str], ...] = tuple(
    button.grid_row() for button in TRANSPORT_BUTTONS
)


def transport_button_at(row: int, col: int) -> tuple[str, str, str, str] | None:
    for button in TRANSPORT_BUTTONS:
        if button.row == row and button.col == col:
            return (button.key, button.label, button.color, button.glyph)
    return None


def transport_cols_for_row(row: int) -> list[int]:
    cols = [button.col for button in TRANSPORT_BUTTONS if button.row == row]
    return sorted(cols) if cols else [0]
