"""RunningHub file transfer for workflow inputs/outputs.

Upload (workflow inputs):
  POST /task/openapi/upload  (multipart: apiKey, fileType=input, file)
  -> data.fileName  e.g. "api/xxx.jpg"  (this is the nodeInfoList fieldValue)

Download (workflow outputs):
  plain HTTP GET of results[].url -> local file.

A node input value for a file-typed param is either a local path (upload it,
with a size/mtime cache) or an already-usable identifier (api/... or a URL).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[0]))  # .../scripts

from rh_pool.client import ET_NETWORK, classify_error  # noqa: E402
from runninghub import NO_WINDOW  # noqa: E402

API_HOST = "https://www.runninghub.cn"
UPLOAD_PATH = "/task/openapi/upload"

FILE_TYPES = {"image", "audio", "video"}


# ------------------------------------------------------------------ classify
def classify(value: object) -> str:
    """How a file param value should be handled.

    'local'   -> exists on disk; must be uploaded
    'rh_id'   -> already an uploaded identifier (api/...)
    'url'     -> http(s) reference; pass through
    'unknown' -> cannot be used
    """
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    v = value.strip()
    if v.startswith(("http://", "https://")):
        return "url"
    if v.startswith("api/"):
        return "rh_id"
    if Path(v).exists():
        return "local"
    return "unknown"


# -------------------------------------------------------------------- upload
def upload_file(api_key: str, file_path: str, timeout: int = 300) -> dict:
    """Upload one input file. Never raises/sys.exit.

    {ok:True, file_name, size} | {ok:False, error_type, error_message, raw}
    """
    path = Path(file_path)
    if not path.exists():
        return {"ok": False, "error_type": "FILE_NOT_FOUND",
                "error_message": f"file not found: {file_path}"}
    cmd = [
        "curl", "-s", "-S", "--fail-with-body", "-X", "POST",
        f"{API_HOST}{UPLOAD_PATH}",
        "-H", f"Host: {API_HOST.split('//')[1]}",
        "-F", f"apiKey={api_key}",
        "-F", "fileType=input",
        "-F", f"file=@{path}",
        "--max-time", str(timeout),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except Exception as exc:
        return {"ok": False, "error_type": ET_NETWORK,
                "error_message": str(exc), "raw": ""}

    body = result.stdout or result.stderr
    try:
        resp = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return {"ok": False, "error_type": ET_NETWORK,
                "error_message": f"invalid upload response: {body[:300]}",
                "raw": body[:500]}

    if result.returncode != 0 or resp.get("code") != 0:
        msg = resp.get("msg", body)
        return {"ok": False, "error_type": classify_error(resp.get("code"), msg),
                "error_message": str(msg), "raw": body[:500]}

    data = resp.get("data") or {}
    file_name = data.get("fileName")
    if not file_name:
        return {"ok": False, "error_type": "UPLOAD_FAILED",
                "error_message": "no fileName in upload response", "raw": body[:500]}
    return {"ok": True, "file_name": str(file_name),
            "size": path.stat().st_size}


def upload_with_cache(store, api_key: str, file_path: str) -> dict:
    """Upload unless an identical file (path+size+mtime) was uploaded before."""
    path = Path(file_path).resolve()
    st = path.stat()
    cached = store.find_upload(str(path), st.st_size, int(st.st_mtime))
    if cached:
        return {"ok": True, "file_name": cached, "cached": True,
                "size": st.st_size}
    result = upload_file(api_key, str(path))
    if result.get("ok"):
        store.record_upload(str(path), st.st_size, int(st.st_mtime),
                            result["file_name"])
        result["cached"] = False
    return result


# ------------------------------------------------------------------ download
def download_file(url: str, output_path: str, timeout: int = 600) -> dict:
    """Download a result URL to a local path. Never raises."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["curl", "-s", "-S", "-L", "-o", str(out), "--max-time", str(timeout), url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except Exception as exc:
        return {"ok": False, "error_type": ET_NETWORK, "error_message": str(exc)}
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        return {"ok": False, "error_type": ET_NETWORK,
                "error_message": (result.stderr or "empty download")[:300]}
    return {"ok": True, "path": str(out.resolve()), "size": out.stat().st_size}
