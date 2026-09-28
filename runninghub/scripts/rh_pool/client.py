"""Safe RunningHub workflow API client for the task pool.

Unlike runninghub.api_post (which prints and sys.exit()s on error), these
helpers never terminate the process. They return structured results so the
pool can record failure types and keep scheduling independent tasks.

  create_workflow(api_key, payload) -> dict: {ok, ...}
  query_task(api_key, task_id)      -> dict: {ok, status, ...}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[0]))  # .../scripts

from runninghub import curl_post_json  # noqa: E402

API_HOST = "https://www.runninghub.cn"
CREATE_PATH = "/task/openapi/create"
QUERY_PATH = "/openapi/v2/query"

# Error type taxonomy (recorded only; no auto-retry this iteration).
ET_AUTH = "AUTH"
ET_BALANCE = "INSUFFICIENT_BALANCE"
ET_WORKFLOW = "WORKFLOW_INVALID"
ET_RENDER = "RENDER_FAILED"
ET_RATELIMIT = "RATE_LIMIT"
ET_NETWORK = "NETWORK"
ET_UNKNOWN = "UNKNOWN"
ET_TASK_NOT_FOUND = "TASK_NOT_FOUND"

_AUTH_HINTS = ("auth", "401", "403", "token", "unauthor", "鉴权", "授权")
_BALANCE_HINTS = ("balance", "insufficient", "余额", "credit", "欠费", "arreas")
_WORKFLOW_HINTS = ("workflow", "node", "param", "invalid", "validate", "工作流", "节点", "参数")
_RATELIMIT_HINTS = ("rate limit", "ratelimit", "too many", "frequency", "频繁", "限流", "429")
_NOTFOUND_HINTS = ("not found", "does not exist", "不存在", "过期", "expired", "已删除")


def classify_error(code: Any = "", message: Any = "") -> str:
    text = f"{code} {message}".lower()
    if any(k in text for k in _NOTFOUND_HINTS):
        return ET_TASK_NOT_FOUND
    if any(k in text for k in _AUTH_HINTS):
        return ET_AUTH
    if any(k in text for k in _BALANCE_HINTS):
        return ET_BALANCE
    if any(k in text for k in _RATELIMIT_HINTS):
        return ET_RATELIMIT
    if any(k in text for k in _WORKFLOW_HINTS):
        return ET_WORKFLOW
    return ET_UNKNOWN


def _decode(result) -> tuple[dict | None, str]:
    """Return (parsed_json, raw_body)."""
    body = result.stdout if result.stdout is not None else result.stderr
    if not body:
        return None, ""
    try:
        return json.loads(body), body
    except (json.JSONDecodeError, TypeError):
        return None, body


def create_workflow(api_key: str, payload: dict, timeout: int = 60) -> dict:
    """Submit one workflow task. Never raises/sys.exit.

    Success: {ok:True, task_id, task_status, raw}
    Failure: {ok:False, error_type, error_code, error_message, raw, http_rc}
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        result = curl_post_json(
            f"{API_HOST}{CREATE_PATH}", payload, headers, timeout=timeout
        )
    except Exception as exc:  # network / curl invocation problem
        return {"ok": False, "error_type": ET_NETWORK, "error_code": "",
                "error_message": str(exc), "raw": "", "http_rc": -1}

    parsed, raw = _decode(result)
    if result.returncode != 0 or parsed is None:
        code = (parsed or {}).get("code", "")
        msg = (parsed or {}).get("msg", raw)
        return {"ok": False, "error_type": classify_error(code, msg),
                "error_code": str(code), "error_message": str(msg),
                "raw": raw[:1000], "http_rc": result.returncode}

    if parsed.get("code") not in (0, None):
        msg = parsed.get("msg", "Unknown error")
        return {"ok": False, "error_type": classify_error(parsed.get("code"), msg),
                "error_code": str(parsed.get("code")), "error_message": str(msg),
                "raw": raw[:1000], "http_rc": result.returncode}

    data = parsed.get("data") or {}
    task_id = data.get("taskId")
    if not task_id:
        return {"ok": False, "error_type": ET_WORKFLOW, "error_code": "",
                "error_message": "No taskId in create response",
                "raw": raw[:1000], "http_rc": result.returncode}

    return {"ok": True, "task_id": str(task_id),
            "task_status": data.get("taskStatus"), "raw": parsed}


def query_task(api_key: str, task_id: str, timeout: int = 30) -> dict:
    """Poll one task. Never raises/sys.exit.

    Pending:  {ok:True, terminal:False, rh_status}
    Success:  {ok:True, terminal:True, status:'SUCCESS', results, cost_money,...}
    Failed:   {ok:True, terminal:True, status:'FAILED', error_type,...}
    Net fail: {ok:False, error_type:NETWORK,...}  (caller may retry the poll later)
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        result = curl_post_json(
            f"{API_HOST}{QUERY_PATH}", {"taskId": task_id}, headers, timeout=timeout
        )
    except Exception as exc:
        return {"ok": False, "error_type": ET_NETWORK, "error_code": "",
                "error_message": str(exc)}

    parsed, raw = _decode(result)
    if result.returncode != 0 or parsed is None:
        code = (parsed or {}).get("code", "")
        msg = (parsed or {}).get("msg", raw)
        return {"ok": False, "error_type": classify_error(code, msg),
                "error_code": str(code), "error_message": str(msg)[:500]}

    rh_status = parsed.get("status", "UNKNOWN")

    if rh_status == "SUCCESS":
        usage = parsed.get("usage") or {}
        cost_time = usage.get("taskCostTime")
        return {
            "ok": True, "terminal": True, "status": "SUCCESS",
            "rh_status": rh_status,
            "results": parsed.get("results") or [],
            # RunningHub returns up to three cost fields; keep each separately.
            "cost_money": _as_float(usage.get("consumeMoney")),
            "cost_third_party_money": _as_float(usage.get("thirdPartyConsumeMoney")),
            "cost_coins": _as_int(usage.get("consumeCoins")),
            "cost_time_s": _as_int(cost_time),
        }

    if rh_status == "FAILED":
        code = parsed.get("errorCode", "")
        msg = parsed.get("errorMessage", "Unknown error")
        return {
            "ok": True, "terminal": True, "status": "FAILED",
            "rh_status": rh_status, "error_code": str(code),
            "error_type": classify_error(code, msg),
            "error_message": str(msg),
        }

    # QUEUED / RUNNING / anything not terminal
    if rh_status in ("QUEUED", "RUNNING"):
        return {"ok": True, "terminal": False, "status": "PENDING",
                "rh_status": rh_status}

    # Empty/unknown status: inspect the error envelope. A task that is gone
    # (cancelled/expired/purged) must become terminal, otherwise the pool could
    # never drain. Hard errors (auth/balance/workflow) are terminal too;
    # everything else is treated as transient and retried on the next poll.
    code = parsed.get("errorCode", "")
    msg = parsed.get("errorMessage", "")
    etype = classify_error(code, msg)
    if etype == ET_TASK_NOT_FOUND or etype in (ET_AUTH, ET_BALANCE, ET_WORKFLOW):
        return {
            "ok": True, "terminal": True, "status": "FAILED",
            "rh_status": rh_status or "UNKNOWN", "error_code": str(code),
            "error_type": etype, "error_message": str(msg) or "task status unknown",
        }
    return {"ok": True, "terminal": False, "status": "PENDING",
            "rh_status": rh_status or "UNKNOWN"}


def _as_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _as_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None
