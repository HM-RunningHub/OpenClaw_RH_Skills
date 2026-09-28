"""Drain notification for the RunningHub task pool.

A single global polling automation (every 30s, command payload, zero LLM)
asynchronously launches a short-lived worker and returns immediately. The
worker advances the pool one step; when the pool has drained it wakes the
originating session via the CLI and then removes the automation -- whether or
not the wake succeeded.

Dedup anchor: the automation's existence means "still polling". Once the wake
command has been issued the automation is removed, so a batch notifies exactly
once and no latch/flag is needed anywhere.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
POOL_DIR = SCRIPT_DIR.parents[1]              # runninghub/
NOTIFY_SCRIPT = SCRIPT_DIR / "notify.py"

# Allow running as a plain script (`python scripts/rh_pool/notify.py run`).
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parents[0]))  # .../scripts


# On Windows a console-subsystem interpreter (python.exe) launched by a
# console-less service gets a visible console window allocated for it -- one
# brief black flash per scheduler tick. The GUI-subsystem interpreter
# (pythonw.exe) allocates no console, so use it for the scheduled command.
def _python_exe() -> str:
    if os.name == "nt":
        w = Path(sys.executable).with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return sys.executable


# Never let a child of ours flash a console either.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) \
    if os.name == "nt" else 0

AUTOMATION_DECLARATION_KEY = "rh-pool-poll"
AUTOMATION_NAME = "rh-pool-poll"
WAKE_MESSAGE = "RunningHub 任务批次已完成：所有任务都到达终态。请读取台账（pool status）并处理产物/通知。"
LOCK_STALE_S = 600


def default_session_key() -> str:
    """Wake-back target when a task carries no originating session."""
    from rh_pool.config import load_config
    return load_config().sessionKey


def poll_every() -> str:
    """Polling cadence for the automation, from config."""
    from rh_pool.config import load_config
    return f"{load_config().pollIntervalSeconds}s"


# --------------------------------------------------------------------- paths
def _lock_path() -> Path:
    from rh_pool.config import load_config
    cfg = load_config()
    return cfg.dataDir / "notify.lock"


def _log_path() -> Path:
    from rh_pool.config import load_config
    cfg = load_config()
    return cfg.dataDir / "notify.log"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ CLI bridge
def _openclaw_bin() -> str | None:
    override = os.environ.get("OPENCLAW_BIN")
    if override and Path(override).exists():
        return override
    found = shutil.which("openclaw")
    if found:
        return found
    cand = Path(sys.executable).parent / "openclaw"
    if cand.exists():
        return str(cand)
    return None


def _run_cli(args: list[str], timeout: int = 120) -> tuple[int, str]:
    exe = _openclaw_bin()
    if not exe:
        return -1, "openclaw CLI not found (set OPENCLAW_BIN)"
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout,
                              stdin=subprocess.DEVNULL,
                              creationflags=_NO_WINDOW)
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)
    return proc.returncode, (proc.stdout or proc.stderr or "")


def _list_jobs() -> list[dict]:
    code, out = _run_cli(["automations", "list", "--all", "--json"])
    if code != 0:
        return []
    try:
        data = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        return data.get("jobs") or data.get("items") or []
    return data if isinstance(data, list) else []


def find_polling_jobs() -> list[dict]:
    return [j for j in _list_jobs()
            if j.get("declarationKey") == AUTOMATION_DECLARATION_KEY
            or j.get("name") == AUTOMATION_NAME]


def ensure_polling_automation() -> dict:
    """Create the single global polling automation if it does not exist."""
    existing = find_polling_jobs()
    if existing:
        return {"action": "reuse",
                "jobId": existing[0].get("id") or existing[0].get("jobId")}

    argv = [_python_exe(), str(NOTIFY_SCRIPT), "launch"]
    args = [
        "automations", "add",
        "--name", AUTOMATION_NAME,
        "--description", "RunningHub pool poll (async short-lived worker)",
        "--every", poll_every(),
        "--command-argv", json.dumps(argv),
        "--command-cwd", str(POOL_DIR),
        # The worker wakes sessions itself; the scheduler must not try to
        # announce job output to a channel.
        "--no-deliver",
        "--declaration-key", AUTOMATION_DECLARATION_KEY,
        "--json",
    ]
    code, out = _run_cli(args, timeout=120)
    if code != 0:
        log(f"ensure_polling_automation FAILED: {out[-400:]}")
        return {"action": "error", "message": out[-400:]}
    job_id = None
    try:
        payload = json.loads(out[out.index("{"):])
        job_id = (payload.get("id") or payload.get("jobId")
                  or (payload.get("job") or {}).get("id"))
    except (ValueError, json.JSONDecodeError):
        pass
    log(f"polling automation created jobId={job_id}")
    return {"action": "created", "jobId": job_id}


def kick_worker() -> dict:
    """Fire one immediate pool tick (detached, fire-and-forget).

    Called right after enqueue so the batch starts within ~1s instead of
    waiting for the scheduler's first 30s boundary. The polling automation
    must already exist as the safety net; this only advances the first tick.
    The worker's single-flight lock makes concurrent kicks harmless.
    """
    rc = mode_launch()
    if rc == 0:
        log("immediate worker kick issued")
        return {"action": "issued"}
    return {"action": "failed", "message": "mode_launch returned non-zero"}


def remove_polling_automation() -> list[str]:
    removed: list[str] = []
    for job in find_polling_jobs():
        jid = job.get("id") or job.get("jobId")
        if not jid:
            continue
        code, _ = _run_cli(["automations", "remove", jid])
        if code == 0:
            removed.append(jid)
    if removed:
        log(f"polling automation removed {removed}")
    return removed


def wake_session(session_key: str, message: str) -> bool:
    """Issue a wake into a session via the CLI, fire-and-forget.

    We only *issue* the command; we never wait for the resulting agent turn
    (which can run for minutes). Waiting here would pin the worker and its lock
    open, so the polling automation would never be removed. Issuing is the
    commitment: the caller removes the automation right after this returns.
    """
    exe = _openclaw_bin()
    if not exe:
        log("wake: openclaw CLI not found")
        return False
    argv = [exe, "agent", "--session-key", session_key, "--message", message]
    kwargs: dict = {"stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                    "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = (_NO_WINDOW | subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(argv, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log(f"wake spawn FAILED session={session_key}: {exc}")
        return False
    log(f"wake issued session={session_key}")
    return True


# -------------------------------------------------------------------- locking
def _acquire_lock() -> bool:
    """Single-instance guard for the short-lived worker (file-based)."""
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Stale lock from a crashed run?
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = 0
        if age > LOCK_STALE_S:
            try:
                path.unlink()
            except OSError:
                return False
            return _acquire_lock()
        return False


def _release_lock() -> None:
    try:
        _lock_path().unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------- modes
def mode_launch() -> int:
    """Fire-and-forget: spawn the worker detached, return immediately."""
    argv = [_python_exe(), str(NOTIFY_SCRIPT), "run"]
    kwargs: dict = {"cwd": str(POOL_DIR),
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                    "close_fds": True}
    if os.name == "nt":
        # Detached + no console window, so neither the launcher's exit kills the
        # worker nor a black console flashes on every tick.
        kwargs["creationflags"] = (_NO_WINDOW | subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(argv, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log(f"launch FAILED: {exc}")
        return 1
    return 0


def mode_run() -> int:
    """Short-lived worker: one pool step; on drain, wake then stop polling."""
    if not _acquire_lock():
        return 0
    try:
        from rh_pool import pool as pool_mod
        from rh_pool.config import load_config
        from rh_pool.store import Store
        from runninghub import resolve_api_key

        cfg = load_config()
        store = Store(cfg.db_path)
        api_key = resolve_api_key(None)
        if not api_key:
            log("run: NO_API_KEY")
            return 2

        summary = pool_mod.run_tick(cfg, api_key)
        counts = summary.get("counts") or {}
        outstanding = counts.get("outstanding", 1)

        if outstanding == 0:
            # Pool drained: wake every distinct origin session, then stop polling.
            sessions = store.distinct_session_keys()
            targets = sessions or [default_session_key()]
            for key in targets:
                wake_session(key, WAKE_MESSAGE)
            store.clear_session_keys()
            # "Issued the wake -> remove, regardless of success."
            remove_polling_automation()
        return 0
    except Exception as exc:  # noqa: BLE001
        log(f"run ERROR {type(exc).__name__}: {exc}")
        return 1
    finally:
        _release_lock()


def main(argv: list[str] | None = None) -> int:
    # Under pythonw the standard streams may be absent; never let a print crash.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "run"
    if mode == "launch":
        return mode_launch()
    if mode == "ensure":
        print(json.dumps(ensure_polling_automation(), ensure_ascii=False, indent=2))
        return 0
    if mode == "remove":
        print(json.dumps({"removed": remove_polling_automation()},
                         ensure_ascii=False, indent=2))
        return 0
    if mode == "status":
        print(json.dumps({"jobs": find_polling_jobs()},
                         ensure_ascii=False, indent=2))
        return 0
    return mode_run()


if __name__ == "__main__":
    sys.exit(main())
