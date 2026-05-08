from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pol_visualizer import SpaceMouseController  # noqa: E402


class FakeStick:
    def get_numbuttons(self) -> int:
        return 3

    def get_button(self, _idx: int) -> int:
        return 0


class FakeSpaceMouse(SpaceMouseController):
    def __init__(self) -> None:
        super().__init__()
        self.available = True
        self._sticks = [FakeStick()]
        self.buttons_held = []
        self.axes = {self.x_axis: 0.0, self.y_axis: 0.0, self.z_axis: 0.0, self.twist_axis: 0.0}

    def _merged_axis(self, axis: int) -> float:
        return float(self.axes.get(axis, 0.0))


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    sm = FakeSpaceMouse()
    sm.xy_repeat_initial_s = 0.20
    sm.xy_repeat_interval_s = 0.18
    sm.y_nav_initial_s = 0.10
    sm.y_nav_interval_s = 0.16
    sm.twist_nav_cooldown_s = 0.20

    sm.axes[sm.x_axis] = 0.70
    _val, _pressed, dr = sm.poll()
    assert_true("right" not in dr, "quick X tilt should not emit immediate right nav")
    time.sleep(0.24)
    _val, _pressed, dr = sm.poll()
    assert_true("right" in dr, "held X tilt should emit right nav")

    sm.axes[sm.x_axis] = 0.0
    sm.poll()
    sm.axes[sm.twist_axis] = 0.50
    val, _pressed, dr = sm.poll()
    assert_true(val != 0.0, "twist should still produce axis value")
    time.sleep(0.90)
    val, _pressed, dr = sm.poll()
    assert_true("twist_cw_hold" not in dr and "twist_ccw_hold" not in dr, "sustained twist must not emit nav/open/close tokens")
    assert_true(val != 0.0, "sustained twist should continue adjusting the current parameter")
    sm.axes[sm.x_axis] = 0.75
    sm.axes[sm.twist_axis] = 0.0
    time.sleep(0.05)
    _val, _pressed, dr = sm.poll()
    assert_true("right" not in dr, "nav should be suppressed shortly after twist")
    time.sleep(0.25)
    _val, _pressed, dr = sm.poll()
    assert_true("right" not in dr, "new tilt still needs deliberate hold after cooldown")
    time.sleep(0.24)
    _val, _pressed, dr = sm.poll()
    assert_true("right" in dr, "held tilt should navigate after cooldown and hold")

    sm.axes[sm.x_axis] = 0.0
    sm.axes[sm.y_axis] = -0.22
    sm.poll()
    time.sleep(0.14)
    _val, _pressed, dr = sm.poll()
    assert_true("up" in dr, "modest held Y tilt should emit up nav")

    sm.axes[sm.x_axis] = 0.26
    sm.axes[sm.y_axis] = 0.24
    sm.poll()
    time.sleep(0.14)
    _val, _pressed, dr = sm.poll()
    assert_true("down" in dr, "modest held Y tilt with X drift should emit down nav")

    sm.axes[sm.x_axis] = 0.35
    sm.axes[sm.y_axis] = 0.0
    sm.poll()
    time.sleep(0.24)
    _val, _pressed, dr = sm.poll()
    assert_true("right" not in dr, "medium X drift below x threshold should not nav right")
    print("PASS: SpaceMouse twist/nav gating")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
