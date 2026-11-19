"""The render-step and feature-settings seams used by phase-2 features."""

import pytest

from sklent import jobs, steps


class FakeSC:
    def __init__(self):
        self.calls = []

    def paint(self, bodies, color, opacity):
        self.calls.append(("paint", color, opacity))


class Pal:
    shaded, wireframe = "#aaa", "#bbb"


def _ctx(tmp_path):
    return steps.StepContext(sc=FakeSC(), design=tmp_path / "d.sc", out_dir=tmp_path, stem="d", opts=None,
                             info=[], bodies=["b1"], box=([0, 0, 0], [1, 1, 1]), palette=Pal(), pitch=0.4,
                             report={}, settings={"exploded": True})


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(steps._STEPS)
    steps._STEPS.clear()
    yield
    steps._STEPS.clear()
    steps._STEPS.update(saved)


def test_steps_run_in_order_and_failures_are_contained(tmp_path):
    ran = []

    def good(ctx):
        ran.append("good")
        ctx.add("d-exploded.png", variant="exploded", width=10, height=10)

    def bad(ctx):
        ran.append("bad")
        ctx.add("d-bad.png", variant="bad")
        raise RuntimeError("boom")

    steps.register_step("b", bad, order=1)
    steps.register_step("g", good, order=2, when=lambda c: c.enabled("exploded"))
    steps.register_step("off", lambda c: ran.append("off"), when=lambda c: c.enabled("nope"))
    ctx = _ctx(tmp_path)
    steps.run_all(ctx)
    assert ran == ["bad", "good"]
    assert [o.file for o in ctx.added] == ["d-exploded.png"]
    assert [p.name for p in ctx.guard] == ["d-exploded.png"]
    assert ctx.report["steps"]["b"]["ok"] is False and "boom" in ctx.report["steps"]["b"]["error"]
    assert ctx.report["steps"]["g"]["files"] == ["d-exploded.png"]
    assert ("paint", "#aaa", 1.0) in ctx.sc.calls  # restored after the failure


def test_fatal_step_stops_the_render(tmp_path):
    def fatal(ctx):
        raise steps.StepFatal("stop")

    steps.register_step("f", fatal)
    with pytest.raises(steps.StepFatal):
        steps.run_all(_ctx(tmp_path))


def test_registered_settings_round_trip(tmp_path, monkeypatch):
    saved = dict(jobs._EXTRA)
    try:
        jobs.register_setting("exploded", False, lambda v: bool(v))
        assert jobs.get_all_settings()["exploded"] is False
        jobs.set_options({"exploded": 1, "seconds": 8})
        allset = jobs.get_all_settings()
        assert allset["exploded"] is True and allset["seconds"] == 8
        jobs.set_options({"seconds": 9})  # other saves keep the feature value
        assert jobs.get_all_settings()["exploded"] is True
        with pytest.raises(ValueError):
            jobs.set_options({"nope": 1})
    finally:
        jobs._EXTRA.clear()
        jobs._EXTRA.update(saved)
