from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from system_q_dsp import ConsoleEngine


RUN_ROOT = Path(__file__).resolve().parent / "SYSTEM_Q_VERIFY_RUNS"


def main() -> None:
    run_dir = RUN_ROOT / f"compressor_limiter_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    engine = ConsoleEngine()
    ch = engine.channels[0]
    block = np.full((2048, 2), 0.8, dtype=np.float32)
    threshold_db = -12.0
    ceiling = float(10.0 ** (threshold_db / 20.0))

    results = []

    with engine._lock:
        ch.comp_enabled = True
        ch.comp_band_enabled = False
        ch.comp_threshold_db = threshold_db
        ch.comp_attack_ms = 0.1
        ch.comp_release_ms = 10.0
        ch.comp_makeup = 1.0
        ch.comp_env = 0.0

        ch.comp_ratio = 4.0
        compressed = engine._apply_compressor(ch, block.copy())
        compressed_peak = float(np.max(np.abs(compressed)))
        results.append(
            {
                "control": "normal compressor ratio does not enter limiter ceiling",
                "passed": compressed_peak > ceiling * 1.05,
                "ratio": ch.comp_ratio,
                "peak": compressed_peak,
                "ceiling": ceiling,
                "gr_db": float(ch.comp_gr_db),
            }
        )

        ch.comp_env = 0.0
        ch.comp_ratio = 20.0
        limited = engine._apply_compressor(ch, block.copy())
        limited_peak = float(np.max(np.abs(limited)))
        results.append(
            {
                "control": "max compressor ratio limits to threshold ceiling",
                "passed": limited_peak <= ceiling + 1e-6,
                "ratio": ch.comp_ratio,
                "peak": limited_peak,
                "ceiling": ceiling,
                "gr_db": float(ch.comp_gr_db),
            }
        )

    report = {
        "run_dir": str(run_dir),
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "results": results,
    }
    (run_dir / "compressor_limiter_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
