from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageDef:
    key: str
    short_label: str
    title: str
    params: tuple[str, ...]
    color: str

    def grid_row(self) -> tuple[str, str, list[str]]:
        return (self.key, self.short_label, list(self.params))


BASE_STAGE_DEFS: tuple[StageDef, ...] = (
    StageDef("pre", "PRE", "Mic Pre", ("TBE", "LPF", "48V", "PHS", "HPF"), "#77f0c6"),
    StageDef("harm", "HRM", "Harmonics", ("TBE", "H1", "H2", "H3", "H4", "H5"), "#ffb757"),
    StageDef("gate", "GTE", "Gate", ("TBE", "THR", "DEP", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"), "#ddc270"),
    StageDef("comp", "CMP", "Compressor", ("TBE", "THR", "RAT", "ATK", "RLS", "GAN", "FRQ", "WDT", "BND"), "#ff6a53"),
    StageDef("eq", "EQ", "EQ", ("TBE", "FRQ", "GAN", "SHP", "BND"), "#75baff"),
    StageDef("trn", "TRN", "Transient", ("FRQ", "ATK", "SUT", "DRV", "BND"), "#36e0dc"),
    StageDef("xct", "XCT", "Exciter", ("FRQ", "ATK", "SUT", "DRV", "BND"), "#c06cff"),
    StageDef("tbe", "TBE", "Tube", ("FRQ", "DRV", "BND"), "#ff8f3a"),
)

AUX_INSERT_STAGE_DEFS: dict[str, StageDef] = {
    "rvb": StageDef("rvb", "RVB", "Reverb", ("TIME", "REF", "MIX", "DMP", "WID", "PRE", "REV"), "#53d6ff"),
    "dly": StageDef("dly", "DLY", "Delay", ("TIME", "FDB", "MIX", "WID", "DMP", "PNG"), "#fcd34d"),
    "mod": StageDef("mod", "MOD", "Modulation", ("TYPE", "RATE", "DEP", "MIX", "FDB", "WID"), "#a78bfa"),
}

MASTER_FILTER_STAGE = StageDef("pre", "FLT", "Filters", ("LPF", "HPF"), "#77f0c6")

STAGE_BY_KEY: dict[str, StageDef] = {
    stage.key: stage for stage in (*BASE_STAGE_DEFS, *AUX_INSERT_STAGE_DEFS.values())
}
STAGE_COLOR: dict[str, str] = {key: stage.color for key, stage in STAGE_BY_KEY.items()}


def base_stage_grid() -> list[tuple[str, str, list[str]]]:
    return [stage.grid_row() for stage in BASE_STAGE_DEFS]


def master_stage_grid() -> list[tuple[str, str, list[str]]]:
    return [MASTER_FILTER_STAGE.grid_row()] + [stage.grid_row() for stage in BASE_STAGE_DEFS if stage.key != "pre"]


def aux_stage_grid(insert_stage: str) -> list[tuple[str, str, list[str]]]:
    insert_def = AUX_INSERT_STAGE_DEFS.get(insert_stage)
    rows = base_stage_grid()
    if insert_def is None:
        return rows
    return [insert_def.grid_row()] + rows


def stage_title(key: str, *, master: bool = False) -> str:
    if master and key == "pre":
        return MASTER_FILTER_STAGE.title
    stage = STAGE_BY_KEY.get(key)
    return stage.title if stage else key.upper()
