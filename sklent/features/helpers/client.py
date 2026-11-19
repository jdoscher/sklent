"""`sklent helper`: render for a Sklent server from another machine (0.2.1).

The loop: claim a render job (idle: wait 10 s, doubling to 60 s), download its inputs,
render the set here with the server's settings snapshot and every feature step, report
progress (which renews the lease and tells us when the job was cancelled), upload the
finished set, clean up. The server files it into Kist and keeps the revision history.

It needs no database, data dir or forge token: everything comes from the server. It runs
in the Linux image (`docker-compose.helper.yml`) or natively, e.g. on a Mac with
SK_SOLIDCRAFT_CLI and SK_FFMPEG pointing at the programs.

Ctrl-C or SIGTERM: the SolidCraft processes stop, the job is reported failed with
"helper stopped" (retry: the server queues it again) and the helper exits.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
from dataclasses import asdict, fields
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

log = logging.getLogger("sklent.helper")

MANIFEST = ".sklent-manifest.json"
IDLE_FIRST, IDLE_MAX = 10.0, 60.0
REFUSED_WAIT = 60.0
PROGRESS_EVERY = 2.0  # seconds between progress reports
HEARTBEAT = 60.0  # re-send the last progress at least this often (renews the lease)


class Stopped(Exception):
    """Ctrl-C or SIGTERM."""


class Cancelled(Exception):
    """The server cancelled the job (or gave it to someone else)."""


def mem_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 2**20, 1)
    except OSError:
        pass
    if platform.system() == "Darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout
            return round(int(out.strip()) / 2**30, 1)
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    return None


def machine_info(renderer: str, max_bodies: int | None = None) -> dict[str, Any]:
    from ...solidcraft import gpu_info, version

    used = gpu_info(renderer)
    return {"solidcraft_version": version(), "renderer": used["renderer"], "gpu": used.get("adapter"),
            "mem_gb": mem_gb(), "max_bodies": max_bodies}


def safe_extract(tar_path: Path, dest: Path) -> None:
    """Unpack plain files only, each at a safe relative path under dest."""
    root = dest.resolve()
    with tarfile.open(tar_path, "r:*") as tar:
        for m in tar.getmembers():
            p = PurePosixPath(m.name)
            if m.isdir():
                continue
            if not m.isfile() or p.is_absolute() or ".." in p.parts:
                raise RuntimeError(f"unsafe member in the inputs: {m.name!r}")
            target = (dest / p).resolve()
            if root not in target.parents:
                raise RuntimeError(f"unsafe member in the inputs: {m.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as src, open(target, "wb") as out:  # type: ignore[union-attr]
                shutil.copyfileobj(src, out, 1 << 20)


def pack_stage(stage: Path, outputs: list, tar_path: Path) -> int:
    """The stage folder as a tar, manifest first. Returns the number of files."""
    files = {p.relative_to(stage).as_posix(): p.stat().st_size
             for p in sorted(stage.rglob("*")) if p.is_file() and not p.is_symlink()}
    manifest = json.dumps({"outputs": [asdict(o) for o in outputs], "files": files}).encode()
    with tarfile.open(tar_path, "w") as tar:
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(manifest)
        info.mtime = int(time.time())
        import io
        tar.addfile(info, io.BytesIO(manifest))
        for name in files:
            tar.add(stage / name, arcname=name, recursive=False)
    return len(files)


class Helper:
    def __init__(self, url: str, token: str, name: str, renderer: str = "gpu", processes: int | None = None,
                 max_bodies: int | None = None, client: httpx.Client | None = None):
        self.url, self.name, self.renderer = url.rstrip("/"), name, renderer
        self.processes, self.max_bodies = processes, max_bodies
        self.http = client or httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {token}"},
                                           timeout=httpx.Timeout(60, read=600), follow_redirects=False)
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.job_id: int | None = None
        self._info: dict | None = None

    # ------------------------------------------------------------ loop

    def info(self) -> dict:
        if self._info is None:
            self._info = {"name": self.name, **machine_info(self.renderer, self.max_bodies)}
        return self._info

    def request_stop(self, *_: Any) -> None:
        if not self.stop.is_set():
            log.info("stopping")
        self.stop.set()
        from ...solidcraft import kill_all
        kill_all()

    def run(self, once: bool = False) -> int:
        idle = IDLE_FIRST
        info = self.info()
        log.info("helper %s: SolidCraft %s, renderer %s (%s), %s GB; asking %s for work", self.name,
                 info["solidcraft_version"], info["renderer"], info["gpu"] or "no adapter found",
                 info["mem_gb"], self.url)
        while not self.stop.is_set():
            try:
                r = self.http.post("/api/helpers/claim", json=info)
            except httpx.HTTPError as exc:
                log.warning("claim: %s", exc)
                if once:
                    return 1
                self.stop.wait(idle)
                idle = min(IDLE_MAX, idle * 2)
                continue
            if r.status_code == 204:
                if once:
                    log.info("nothing to render")
                    return 0
                self.stop.wait(idle)
                idle = min(IDLE_MAX, idle * 2)
                continue
            if r.status_code == 409:
                log.error("refused: %s", _detail(r))
                if once:
                    return 2
                self.stop.wait(REFUSED_WAIT)
                continue
            if r.status_code in (401, 403):
                log.error("the server refused the token (%s): %s", r.status_code, _detail(r))
                return 3
            if r.status_code >= 400:
                log.warning("claim: %s %s", r.status_code, _detail(r))
                if once:
                    return 1
                self.stop.wait(idle)
                continue
            idle = IDLE_FIRST
            self.do_job(r.json())
            if once:
                return 0
        return 0

    # ------------------------------------------------------------ one job

    def _q(self) -> dict:
        return {"name": self.name}

    def report(self, fraction: float, message: str) -> None:
        """Send progress; mark the job cancelled when the server says so."""
        if self.job_id is None:
            return
        try:
            r = self.http.post(f"/api/helpers/jobs/{self.job_id}/progress", params=self._q(),
                               json={"fraction": fraction, "message": message}, timeout=30)
            if r.status_code == 200 and r.json().get("cancel"):
                self.cancel.set()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("progress: %s", exc)

    def fail(self, error: str, retry: bool = False) -> None:
        try:
            self.http.post(f"/api/helpers/jobs/{self.job_id}/fail", params=self._q(),
                           json={"error": error[:2000], "retry": retry}, timeout=30)
        except httpx.HTTPError as exc:
            log.warning("reporting the failure: %s", exc)

    def do_job(self, claim: dict) -> None:
        from ... import features
        from ...render import RenderOptions, render_set
        from ...repo_config import OVERRIDES
        from ...solidcraft import kill_all
        from ..specs import meta

        job, snapshot = claim["job"], claim["settings_snapshot"]
        self.job_id = job["id"]
        self.cancel.clear()
        design = snapshot["design"]
        log.info("job %s: %s/%s %s", job["id"], design.get("owner"), design.get("repo"), design.get("path"))
        tmp = Path(tempfile.mkdtemp(prefix=f"sklent-helper-{job['id']}-"))
        latest = {"f": 0.0, "m": "starting", "sent": 0.0}
        beat_stop = threading.Event()

        def heartbeat() -> None:
            while not beat_stop.wait(HEARTBEAT / 4):
                if time.monotonic() - latest["sent"] >= HEARTBEAT:
                    latest["sent"] = time.monotonic()
                    self.report(latest["f"], latest["m"])
                    if self.cancel.is_set():
                        kill_all()

        def progress(f: float, m: str) -> None:
            if self.stop.is_set():
                raise Stopped("helper stopped")
            if self.cancel.is_set():
                raise Cancelled("cancelled")
            latest.update(f=f, m=m)
            if time.monotonic() - latest["sent"] >= PROGRESS_EVERY or f >= 1:
                latest["sent"] = time.monotonic()
                self.report(f, m)
                if self.cancel.is_set():
                    kill_all()
                    raise Cancelled("cancelled")

        beat = threading.Thread(target=heartbeat, daemon=True, name="helper-heartbeat")
        beat.start()
        t0 = time.monotonic()
        try:
            features.load()
            OVERRIDES[design["id"]] = snapshot.get("_repo_config") or {}
            meta.REPO_FILE_HOOK[:] = [self._repo_file]
            inputs = tmp / "inputs.tar"
            with self.http.stream("GET", f"/api/helpers/jobs/{job['id']}/inputs.tar", params=self._q()) as r:
                if r.status_code != 200:
                    r.read()
                    raise Cancelled(f"inputs: {r.status_code} {_detail(r)}") if r.status_code == 409 else \
                        RuntimeError(f"inputs: {r.status_code} {_detail(r)}")
                with open(inputs, "wb") as fh:
                    for chunk in r.iter_bytes(1 << 20):
                        fh.write(chunk)
            work = tmp / "in"
            safe_extract(inputs, work)
            inputs.unlink()
            local = work / claim["design_file"]
            known = {f.name for f in fields(RenderOptions)}
            opts = RenderOptions(**{k: v for k, v in snapshot.items() if k in known})
            stage = tmp / "out" / claim.get("set_id", "set")
            progress(0.0, "rendering on " + self.name)
            outputs, report = render_set(local, stage, claim["stem"], opts, progress, processes=self.processes,
                                         settings=snapshot, renderer=self.renderer, host=self.name)
            try:
                from ..inputs.links import report_for
                report["inputs"] = report_for(local)
            except ImportError:
                pass
            report.setdefault("timings_s", {})["helper_total"] = round(time.monotonic() - t0, 1)
            (stage / "report.json").write_text(json.dumps(report, indent=2))
            if self.stop.is_set():
                raise Stopped("helper stopped")
            if self.cancel.is_set():
                raise Cancelled("cancelled")
            self.report(1.0, "uploading")
            tar = tmp / "result.tar"
            n = pack_stage(stage, outputs, tar)
            shutil.rmtree(stage, ignore_errors=True)
            with open(tar, "rb") as fh:
                r = self.http.post(f"/api/helpers/jobs/{job['id']}/result", params=self._q(), content=fh,
                                   headers={"Content-Type": "application/x-tar"},
                                   timeout=httpx.Timeout(60, read=3600, write=3600))
            if r.status_code == 409:
                raise Cancelled(_detail(r))
            if r.status_code >= 400:
                raise RuntimeError(f"upload refused: {r.status_code} {_detail(r)}")
            log.info("job %s done in %.0f s (%d files): %s", job["id"], time.monotonic() - t0, n,
                     r.json().get("message"))
        except Cancelled as exc:
            log.info("job %s cancelled by the server (%s)", job["id"], exc)
        except BaseException as exc:  # noqa: BLE001 - every failure is reported
            if self.stop.is_set() or isinstance(exc, Stopped | KeyboardInterrupt):
                self.stop.set()
                log.info("job %s: helper stopped; the server queues it again", job["id"])
                self.fail("helper stopped", retry=True)
            elif self.cancel.is_set():
                log.info("job %s cancelled by the server", job["id"])
            else:
                log.warning("job %s failed: %s", job["id"], exc)
                self.fail(str(exc) or exc.__class__.__name__)
        finally:
            beat_stop.set()
            kill_all()
            OVERRIDES.pop(design["id"], None)
            meta.REPO_FILE_HOOK.clear()
            shutil.rmtree(tmp, ignore_errors=True)
            self.job_id = None

    def _repo_file(self, row: dict, rel_path: str, max_bytes: int = 1 << 20) -> bytes | None:
        if self.job_id is None:
            return None
        try:
            r = self.http.get(f"/api/helpers/jobs/{self.job_id}/repo-file", params={**self._q(), "path": rel_path})
        except httpx.HTTPError:
            return None
        return r.content[:max_bytes] if r.status_code == 200 else None


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail") or r.text)[:500]
    except ValueError:
        return r.text[:500]


def main(url: str, token: str, name: str, renderer: str = "gpu", processes: int | None = None,
         once: bool = False, max_bodies: int | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    h = Helper(url, token, name, renderer, processes, max_bodies)
    signal.signal(signal.SIGTERM, h.request_stop)
    signal.signal(signal.SIGINT, h.request_stop)
    try:
        return h.run(once=once)
    finally:
        h.http.close()


def read_token(token_file: str | None) -> str:
    if token_file:
        return Path(token_file).expanduser().read_text().strip()
    return os.environ.get("SK_HELPER_TOKEN", "").strip()
