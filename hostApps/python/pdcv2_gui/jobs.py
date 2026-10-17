"""
Job queue. One job runs at a time because the bench (supplies, ZCU, controller) is a single shared resource.

A job is a command line. Mode jobs carry a snapshot of the configs they were queued with. Stop sends SIGINT, which the
scripts handle by ramping the supplies down; a hard kill is a separate, confirmed action.
"""
from __future__ import annotations
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

HOME = Path(os.environ.get("PDCV2_GUI_HOME", Path.home() / ".pdcv2_gui"))
JOBS_DIR = HOME / "jobs"
LOGS_DIR = HOME / "logs"
QUEUE_FILE = HOME / "queue.json"

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ERROR = re.compile(r"(?i)\b(error|exception|fatal|critical|failed|failure)\b")
WARNING = re.compile(r"(?i)\bwarn(ing)?\b")
TRACEBACK = re.compile(r"\s*Traceback \(most recent call last\)")
PERCENT = re.compile(r"(\d{1,3})%\|")


@dataclass
class Job:
    title: str
    cmd: list[str]
    cwd: str
    mode: str = ""
    run_folder: str = ""
    summary: str = ""
    details: str = ""
    snapshot: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    enabled: bool = True
    status: str = "queued"
    started: float = 0.0
    finished: float = 0.0
    exit_code: int | None = None
    errors: int = 0
    warnings: int = 0
    progress: int = -1

    @property
    def duration(self) -> float:
        if not self.started:
            return 0.0
        return (self.finished or time.time()) - self.started

    @property
    def log_path(self) -> Path:
        return LOGS_DIR / f"{self.id}.log"

    @property
    def command_text(self) -> str:
        return shlex.join(self.cmd)


def classify(job_state: dict, text: str) -> str:
    """Level of one output line: info, warn or error. Tracebacks stay error until their exception line"""
    plain = ANSI.sub("", text)
    if TRACEBACK.match(plain):
        job_state["tb"] = True
        return "error"
    if job_state.get("tb"):
        if not plain.strip():
            job_state["tb"] = False
            return "info"
        if not plain.startswith((" ", "\t")):
            job_state["tb"] = False
        return "error"
    if ERROR.search(plain):
        return "error"
    return "warn" if WARNING.search(plain) else "info"

def preflight(python: str, script: str, cwd: str, config_dir: Path, timeout: int = 90) -> tuple[bool, str]:
    """Runs the script's own --show-config on a snapshot: loads and validates the config, never touches hardware"""
    try:
        r = subprocess.run([python, script, "--show-config", "--config-dir", str(config_dir)],
                           cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as ex:
        return False, f"could not run the config check: {ex}"
    return r.returncode == 0, (r.stderr or r.stdout).strip() if r.returncode else ""


class JobQueue(QObject):
    changed = Signal()
    line = Signal(str, str, str)          # job id (empty for the GUI itself), level, text
    progress = Signal(str, int, str)      # job id, percent or -1, live text
    state = Signal(str)                   # idle | running | paused
    stuck = Signal(str)                   # job id that ignored SIGINT for a while

    def __init__(self):
        super().__init__()
        self.jobs: list[Job] = []
        self.on_error = "stop"
        self.gap_s = 0
        self.pause_after = False
        self._proc: QProcess | None = None
        self._cur: Job | None = None
        self._buf = ""
        self._cls: dict = {}
        self._stop_requested = False
        self._running = False
        self._log_file = None
        self._prompt_timer = QTimer(singleShot=True, interval=500)
        self._prompt_timer.timeout.connect(self._flush_prompt)
        self._stuck_timer = QTimer(singleShot=True, interval=60_000)
        self._stuck_timer.timeout.connect(lambda: self._cur and self.stuck.emit(self._cur.id))
        self._gap_timer = QTimer(singleShot=True)
        self._gap_timer.timeout.connect(self._start_next)
        self.load()

    # ---------------------------------------------------------- persistence
    def save(self) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        QUEUE_FILE.write_text(json.dumps([asdict(j) for j in self.jobs], indent=1))

    def load(self) -> None:
        if not QUEUE_FILE.is_file():
            return
        try:
            for d in json.loads(QUEUE_FILE.read_text()):
                job = Job(**d)
                if job.status == "running":
                    job.status = "stopped"
                self.jobs.append(job)
        except (ValueError, TypeError):
            self.jobs = []

    # ------------------------------------------------------------- editing
    def add(self, job: Job) -> None:
        self.jobs.append(job)
        self._touch()

    def index(self, job_id: str) -> int:
        return next(i for i, j in enumerate(self.jobs) if j.id == job_id)

    def job(self, job_id: str) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def remove(self, ids: list[str]) -> None:
        for j in [j for j in self.jobs if j.id in ids and j is not self._cur]:
            self.jobs.remove(j)
            shutil.rmtree(JOBS_DIR / j.id, ignore_errors=True)
        self._touch()

    def clear_finished(self) -> None:
        self.remove([j.id for j in self.jobs if j.status in ("done", "failed", "stopped", "skipped")])

    def move(self, job_id: str, delta: int) -> None:
        i = self.index(job_id)
        j = max(0, min(len(self.jobs) - 1, i + delta))
        self.jobs.insert(j, self.jobs.pop(i))
        self._touch()

    def duplicate(self, job_id: str) -> None:
        src = self.job(job_id)
        new = Job(**{**asdict(src), "id": uuid.uuid4().hex[:8], "status": "queued", "started": 0.0, "finished": 0.0,
                     "exit_code": None, "errors": 0, "warnings": 0, "progress": -1})
        if src.snapshot:
            new.snapshot = str(JOBS_DIR / new.id / "configs")
            shutil.copytree(src.snapshot, new.snapshot)
            new.cmd = [new.snapshot if c == src.snapshot else c for c in new.cmd]
        self.jobs.insert(self.index(job_id) + 1, new)
        self._touch()

    def requeue(self, job_id: str) -> None:
        j = self.job(job_id)
        if j is not self._cur:
            j.status, j.started, j.finished, j.exit_code, j.errors, j.warnings, j.progress = "queued", 0.0, 0.0, None, 0, 0, -1
            self._touch()

    def set_enabled(self, job_id: str, enabled: bool) -> None:
        self.job(job_id).enabled = enabled
        self._touch()

    def _touch(self) -> None:
        self.save()
        self.changed.emit()

    # ------------------------------------------------------------- running
    @property
    def running(self) -> bool:
        """True from Run until the queue stops, including the pause between two jobs"""
        return self._running

    @property
    def current(self) -> Job | None:
        return self._cur

    def pending(self) -> list[Job]:
        return [j for j in self.jobs if j.status == "queued" and j.enabled]

    def start(self) -> None:
        if self._running or not self.pending():
            return
        self._running = True
        self.pause_after = False
        self._stop_requested = False
        self.state.emit("running")
        self._start_next()

    def _start_next(self) -> None:
        todo = self.pending()
        if not todo or self._stop_requested:
            return self._finish_queue("queue finished" if not todo else "queue stopped")
        job = todo[0]
        self._cur, self._buf, self._cls = job, "", {}
        job.status, job.started, job.finished, job.exit_code = "running", time.time(), 0.0, None
        job.errors = job.warnings = 0
        job.progress = -1
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._log_file = open(job.log_path, "w", encoding="utf-8")
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(job.cwd)
        proc.readyReadStandardOutput.connect(self._read)
        proc.finished.connect(self._done)
        proc.errorOccurred.connect(self._error)
        self._proc = proc
        self.line.emit(job.id, "gui", f"Started: {job.command_text}")
        proc.start(job.cmd[0], job.cmd[1:])
        self._touch()

    def _read(self) -> None:
        text = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        job = self._cur
        buf = (self._buf + text).replace("\r\n", "\n")
        *lines, rest = buf.split("\n")
        for raw in lines:
            segs = [s for s in raw.split("\r") if s]
            self._emit(job, segs[-1] if segs else "")
        self._buf = rest
        live = [s for s in rest.split("\r") if s]
        if live and (PERCENT.search(live[-1]) or "\r" in rest):
            self._progress(job, live[-1])
        elif rest:
            self._prompt_timer.start()

    def _progress(self, job: Job, text: str) -> None:
        m = PERCENT.search(text)
        job.progress = int(m[1]) if m else job.progress
        self.progress.emit(job.id, job.progress, ANSI.sub("", text).strip())

    def _emit(self, job: Job, text: str) -> None:
        if PERCENT.search(text):
            self._progress(job, text)
        level = classify(self._cls, text)
        job.errors += level == "error"
        job.warnings += level == "warn"
        if self._log_file:
            self._log_file.write(ANSI.sub("", text) + "\n")
            self._log_file.flush()
        self.line.emit(job.id, level, text)
        if level != "info":
            self.changed.emit()

    def _flush_prompt(self) -> None:
        """Text that stays without a newline is a prompt such as input(): show it and wait for the user"""
        if self._cur and self._buf and "\r" not in self._buf and not PERCENT.search(self._buf):
            text, self._buf = self._buf, ""
            self.line.emit(self._cur.id, "prompt", text)

    def send_input(self, text: str) -> None:
        if self._proc and self._cur:
            self._proc.write((text + "\n").encode())
            self.line.emit(self._cur.id, "gui", f"> {text}")

    def _error(self, err) -> None:
        if err == QProcess.FailedToStart and self._cur:
            self.line.emit(self._cur.id, "error", f"Could not start: {self._cur.cmd[0]}")
            self._done(-1, QProcess.CrashExit)

    def _done(self, code: int, status) -> None:
        job, proc = self._cur, self._proc
        if job is None:
            return
        self._flush_prompt()
        if self._buf:
            self._emit(job, self._buf.split("\r")[-1])
        self._stuck_timer.stop()
        job.exit_code, job.finished = code, time.time()
        if self._stop_requested:
            job.status = "stopped"
        else:
            job.status = "done" if code == 0 and status == QProcess.NormalExit else "failed"
        mins = divmod(int(job.duration), 60)
        self.line.emit(job.id, "gui" if job.status == "done" else "error",
                       f"Finished: {job.status} (exit code {code}) after {mins[0]} min {mins[1]} s"
                       + (f", {job.errors} error line(s)" if job.errors else ""))
        if self._log_file:
            self._log_file.close()
            self._log_file = None
        self._cur, self._proc = None, None
        proc.deleteLater()
        self._touch()
        if self._stop_requested:
            return self._finish_queue("queue stopped")
        if job.status == "failed" and self.on_error == "stop":
            return self._finish_queue("queue halted by the failed job (change this with 'On error')")
        if self.pause_after:
            return self._finish_queue("queue paused after the current job", paused=True)
        if self.pending():
            self._gap_timer.start(int(self.gap_s * 1000))
        else:
            self._finish_queue("queue finished")

    def _finish_queue(self, why: str, paused: bool = False) -> None:
        self._running = False
        self.pause_after = False
        self.line.emit("", "gui", why.capitalize())
        self.state.emit("paused" if paused else "idle")
        self.changed.emit()

    # ------------------------------------------------------------ stopping
    def stop(self) -> None:
        """Interrupt the running job (SIGINT, the scripts ramp the supplies down) and do not start the next"""
        self._stop_requested = True
        self._gap_timer.stop()
        if self._proc and self._proc.processId():
            os.kill(self._proc.processId(), signal.SIGINT)
            self.line.emit(self._cur.id, "gui", "Interrupt sent. The script ramps the supplies down before it exits.")
            self._stuck_timer.start()
        elif self._running and not self._cur:
            self._finish_queue("queue stopped")

    def terminate(self) -> None:
        if self._proc:
            self._proc.terminate()
            self.line.emit(self._cur.id, "error", "SIGTERM sent")

    def kill(self) -> None:
        if self._proc:
            self._proc.kill()
            self.line.emit(self._cur.id, "error", "SIGKILL sent: supplies may still be on, check them")
