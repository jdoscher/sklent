import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from sklent import render, steps
from sklent.render import RenderOptions, extra_processes, render_set
from sklent.solidcraft import SolidCraft, SolidCraftError

GB = 2**30


class FakeSC:
    """Stands in for solidcraft-cli: writes small grey frames, records what it was asked."""

    instances: list["FakeSC"] = []
    frame_s = 0.0
    fail_on: tuple[int, int] | None = None  # (instance number, shot number)
    lock = threading.Lock()

    def __init__(self, design: Path, out_dir: Path):
        with FakeSC.lock:
            self.n = len(FakeSC.instances)
            FakeSC.instances.append(self)
        self.proc = SimpleNamespace(pid=-1)
        self.shots: list[Path] = []
        self.paints: list[str] = []
        self.killed = False

    def bodies(self):
        return [{"name": "a", "visible": True, "bbox": {"min": [-10, -10, 0], "max": [10, 10, 20]}}]

    bounds = staticmethod(SolidCraft.bounds)

    def paint(self, bodies, color, opacity):
        self.paints.append("wireframe" if opacity == 0 else "shaded")

    def screenshot(self, path: Path, camera: dict, width: int, height: int):
        if self.killed:
            raise SolidCraftError("killed")
        time.sleep(FakeSC.frame_s)
        if FakeSC.fail_on == (self.n, len(self.shots)):
            raise SolidCraftError(f"worker {self.n} broke")
        Image.new("RGB", (8, 8), (128, 128, 128)).save(path)
        self.shots.append(path)

    def kill(self):
        self.killed = True

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def fake(monkeypatch):
    FakeSC.instances, FakeSC.frame_s, FakeSC.fail_on = [], 0.0, None
    monkeypatch.setattr(render, "SolidCraft", FakeSC)
    monkeypatch.setattr(render, "encode", lambda frames, out, *a, **k: out.write_bytes(b"mp4"))
    monkeypatch.setattr(render, "encode_gif", lambda frames, out, *a, **k: out.write_bytes(b"gif"))
    monkeypatch.setattr(steps, "_STEPS", {})  # the render core alone, without feature steps
    return FakeSC


OPTS = dict(seconds=2, fps=24)  # 48 frames per style and aspect: 192 frames + 4 stills


def _frame_names(out: Path) -> list[str]:
    return sorted(p.name for p in out.glob("_frames/*/*.png"))


def _check_set(tmp_path: Path, outputs, fake):
    assert len(outputs) == 12  # 2 styles x (4 movies + 2 stills)
    shots = [p for sc in fake.instances for p in sc.shots]
    frames = [p for p in shots if p.parent.parent.name == "_frames"]
    assert len(frames) == 192 and len(set(frames)) == 192  # every frame exactly once
    for d in {p.parent for p in frames}:
        assert sorted(p.name for p in frames if p.parent == d) == [f"f{i:04d}.png" for i in range(48)]


def test_small_design_stays_in_one_process(tmp_path, fake):
    outputs, report = render_set(Path("d.sc"), tmp_path, "d", RenderOptions(**OPTS), processes=4)
    assert report["processes"] == 1 and len(fake.instances) == 1
    _check_set(tmp_path, outputs, fake)
    assert set(report["timings_s"]) == {"load", "frames", "stills", "guard_and_encode"}


def test_slow_design_fans_out(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(render, "FAN_OUT_MS", 1)
    fake.frame_s = 0.004
    outputs, report = render_set(Path("d.sc"), tmp_path, "d", RenderOptions(**OPTS), processes=3)
    assert report["processes"] == 3 and len(fake.instances) == 3
    assert all(sc.shots for sc in fake.instances)  # every process did some frames
    _check_set(tmp_path, outputs, fake)
    for sc in fake.instances[1:]:
        assert len(sc.paints) <= 4  # repaints only where a style changes, not per frame


def test_a_failing_worker_fails_the_set_and_stops_the_rest(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(render, "FAN_OUT_MS", 1)
    fake.frame_s = 0.004
    fake.fail_on = (2, 3)
    with pytest.raises(SolidCraftError, match="worker 2 broke"):
        render_set(Path("d.sc"), tmp_path, "d", RenderOptions(**OPTS), processes=3)
    assert all(sc.killed for sc in fake.instances if sc.n != 2)
    assert sum(len(sc.shots) for sc in fake.instances) < 192


@pytest.mark.parametrize("args, expect", [
    ((4, 15, 900, 1, None, None), 0),  # fast frames: one process
    ((1, 550, 900, 125, None, None), 0),  # SK_RENDER_PROCESSES=1
    ((4, 550, 900, 125, None, None), 3),  # SELENE-like, memory unknown
    ((4, 550, 900, 125, int(6.7 * GB), 20 * GB), 2),  # memory holds two more
    ((4, 550, 900, 125, int(6.7 * GB), 5 * GB), 0),  # memory holds none
    ((4, 60, 900, 125, None, None), 0),  # 54 s of frames left: done before a load (125 s)
])
def test_extra_processes(args, expect):
    assert extra_processes(*args) == expect
