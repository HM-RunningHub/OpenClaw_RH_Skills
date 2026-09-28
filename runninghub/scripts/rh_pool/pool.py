"""RunningHub async workflow task pool — core orchestration / CLI.

Commands:
  enqueue   Add one or more workflow jobs to the global pool (PENDING).
  tick      One non-blocking advance: dispatch -> poll states -> dispatch
            (refill slots freed this tick) -> download outputs.
  status    Query the ledger (counts / task detail).
  reconcile Re-poll all DISPATCHED tasks and sync state (after restart).

The pool is a pure executor + ledger: it answers "accept work" and "is it
done". Waiting and notification belong to the caller; when a batch drains, a
short-lived worker wakes the originating session (see rh_pool/notify.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parents[0]))  # .../scripts

from rh_pool.client import create_workflow, query_task  # noqa: E402
from rh_pool.config import load_config  # noqa: E402
from rh_pool.store import Store, row_to_dict  # noqa: E402
from rh_pool import notify, transfer, workflow_def  # noqa: E402
from runninghub import resolve_api_key  # noqa: E402


# --------------------------------------------------------------------- parsing
def parse_node_arg(arg: str) -> dict:
    """nodeId:fieldName=value -> {nodeId, fieldName, fieldValue}."""
    ci = arg.find(":")
    ei = arg.find("=", ci + 1) if ci != -1 else -1
    if ci == -1 or ei == -1:
        raise ValueError(f"invalid --node '{arg}', expected nodeId:fieldName=value")
    raw = arg[ei + 1:]
    try:
        value: object = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        value = raw
    return {"nodeId": arg[:ci], "fieldName": arg[ci + 1:ei], "fieldValue": value}


def build_job_from_args(args) -> dict:
    nodes = [parse_node_arg(n) for n in (args.node or [])]
    instance = args.instance_type or "default"
    job = {
        "workflow_id": args.workflow_id,
        "instance_type": instance,
        "node_overrides": nodes,
    }
    if getattr(args, "output", None):
        job["outputDir"] = args.output
    return job


def _parse_kv(pairs) -> dict:
    out: dict = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"invalid --param '{pair}', expected name=value")
        k, v = pair.split("=", 1)
        try:
            out[k] = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            out[k] = v
    return out


def _coerce_scalar(p, value):
    """Coerce a non-file param value to the type the node expects."""
    if p.type == "json":
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if p.type == "int":
        return int(value)
    if p.type == "float":
        return float(value)
    if p.type == "bool":
        return bool(value)
    if p.type == "enum":
        if p.enum and value not in p.enum:
            raise ValueError(f"param '{p.name}'='{value}' not in enum {p.enum}")
        return value
    return value if isinstance(value, str) else str(value)


def _resolve_job(job: dict, store: Store, api_key: str | None, cfg) -> dict:
    """Turn a requested job into a stored job: resolve the task type, upload any
    local file inputs (cached), and build node_overrides. Raises ValueError.
    """
    if job.get("type"):
        t = workflow_def.get_task_type(job["type"])
        instance = (job.get("instance_type") or t.instanceType
                    or cfg.defaultInstanceType)
        params = job.get("params") or {}
        unknown = set(params) - {p.name for p in t.params}
        if unknown:
            raise ValueError(f"unknown params {sorted(unknown)} for type '{t.typeId}'")
        nodes: list[dict] = []
        inputs: list[dict] = []
        for p in t.params:
            if p.name in params:
                value = params[p.name]
            elif p.default is not None:
                value = p.default
            elif p.required:
                raise ValueError(f"type '{t.typeId}': required param '{p.name}' missing")
            else:
                continue
            if p.type in transfer.FILE_TYPES:
                kind = transfer.classify(value)
                if kind == "local":
                    if not api_key:
                        raise ValueError("no API key available for upload")
                    up = transfer.upload_with_cache(store, api_key, value)
                    if not up.get("ok"):
                        raise ValueError(
                            f"upload failed for '{p.name}': {up.get('error_message')}")
                    field_value = up["file_name"]
                    inputs.append({"param": p.name, "fieldName": p.fieldName,
                                   "localPath": str(Path(value).resolve()),
                                   "rhFileName": up["file_name"],
                                   "cached": bool(up.get("cached"))})
                elif kind in ("rh_id", "url"):
                    field_value = value
                    inputs.append({"param": p.name, "fieldName": p.fieldName,
                                   "localPath": None, "rhFileName": value,
                                   "cached": True})
                else:
                    raise ValueError(
                        f"param '{p.name}': file not found or unusable: {value!r}")
            else:
                field_value = _coerce_scalar(p, value)
            nodes.append({"nodeId": p.nodeId, "fieldName": p.fieldName,
                          "fieldValue": field_value})
        nodes.extend(t.fixedOverrides)
        request = {"type": t.typeId, "workflowId": t.workflowId,
                   "instanceType": instance}
        if job.get("outputDir"):
            request["outputDir"] = job["outputDir"]
        return {"workflow_id": t.workflowId, "instance_type": instance,
                "node_overrides": nodes, "request_json": request,
                "inputs": inputs}

    # Raw mode: caller supplies workflow_id + ready node values (rh ids / urls
    # or plain scalars); no upload logic is applied.
    if not job.get("workflow_id"):
        raise ValueError("job needs 'type' or 'workflow_id'")
    instance = job.get("instance_type") or cfg.defaultInstanceType
    request = {"workflowId": job["workflow_id"], "instanceType": instance}
    if job.get("outputDir"):
        request["outputDir"] = job["outputDir"]
    return {"workflow_id": job["workflow_id"], "instance_type": instance,
            "node_overrides": job.get("node_overrides") or [],
            "request_json": request, "inputs": job.get("inputs") or []}


# ------------------------------------------------------------------- commands
def cmd_enqueue(args) -> int:
    cfg = load_config()
    store = Store(cfg.db_path)

    if args.from_file:
        jobs = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
        if isinstance(jobs, dict):
            jobs = [jobs]
    else:
        if args.type:
            jobs = [{"type": args.type, "params": _parse_kv(args.param),
                     "instance_type": args.instance_type,
                     "outputDir": args.output}]
        elif args.workflow_id:
            jobs = [build_job_from_args(args)]
        else:
            print("enqueue requires --type, --workflow-id, or --from-file",
                  file=sys.stderr)
            return 2

    # Uploads (for typed jobs with local file inputs) need the API key.
    api_key = resolve_api_key(None)
    resolved: list[dict] = []
    try:
        for job in jobs:
            resolved.append(_resolve_job(job, store, api_key, cfg))
    except (ValueError, workflow_def.DefinitionError) as exc:
        print(json.dumps({"error": "ENQUEUE_REJECTED", "message": str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 2

    ids = store.enqueue(resolved, session_key=_current_session_key())
    # Ensure the single global polling automation exists so this batch will be
    # reported when it drains. Best-effort: never fail an enqueue over it.
    notify_result = {"action": "skipped"}
    kick_result = {"action": "skipped"}
    if not getattr(args, "no_notify", False):
        try:
            notify_result = notify.ensure_polling_automation()
        except Exception as exc:  # noqa: BLE001
            notify_result = {"action": "error", "message": str(exc)}
        # Safety net (automation) is in place -> fire one immediate tick so the
        # batch starts now instead of waiting for the first 30s boundary.
        if notify_result.get("action") in ("created", "reuse"):
            try:
                kick_result = notify.kick_worker()
            except Exception as exc:  # noqa: BLE001
                kick_result = {"action": "failed", "message": str(exc)}
    print(json.dumps({"enqueued": len(ids), "poolIds": ids,
                      "notify": notify_result, "kick": kick_result,
                      "counts": store.count_status()}, ensure_ascii=False, indent=2))
    return 0


def _current_session_key() -> str:
    """Originating session for wake-back.

    The caller (skill/session) may pass OPENCLAW_SESSION_KEY; otherwise use the
    configured default (config.sessionKey).
    """
    return os.environ.get("OPENCLAW_SESSION_KEY") or notify.default_session_key()


def _dispatch_pending(store: Store, api_key: str, concurrency: int) -> dict:
    active = store.get_active()
    free = max(0, concurrency - len(active))
    summary = {"dispatched": 0, "submit_failed": 0}
    if free == 0:
        return summary
    for row in store.get_pending(free):
        payload: dict = {"apiKey": api_key, "workflowId": row["workflow_id"]}
        nodes = _loads(row["node_overrides"])
        if nodes:
            payload["nodeInfoList"] = nodes
        if row["instance_type"] and row["instance_type"] != "default":
            payload["instanceType"] = row["instance_type"]
        result = create_workflow(api_key, payload)
        if result.get("ok"):
            store.mark_dispatched(row["id"], result["task_id"])
            summary["dispatched"] += 1
        else:
            store.mark_submit_failed(
                row["id"], result.get("error_type", "UNKNOWN"),
                result.get("error_code", ""), result.get("error_message", ""),
            )
            summary["submit_failed"] += 1
    return summary


def _download_outputs(store: Store, row, results: list[dict], cfg) -> list[dict]:
    """Download result files for a finished task into the output tree.

    Layout: <output_root>/<poolId>_<nodeId>_<idx>.<ext>  (or per-job outputDir).
    """
    req = _loads(row["request_json"]) or {}
    base = Path(req.get("outputDir")) if req.get("outputDir") else (cfg.output_root / str(row["id"]))
    downloads: list[dict] = []
    for idx, item in enumerate(results or []):
        url = item.get("url") or item.get("outputUrl")
        if not url:
            continue
        ext = item.get("outputType") or "bin"
        node = item.get("nodeId") or "out"
        target = base / f"{row['id']}_{node}_{idx}.{ext}"
        dl = transfer.download_file(url, str(target))
        record = {"nodeId": node, "url": url, "outputType": ext,
                  "path": dl.get("path"), "size": dl.get("size"),
                  "ok": bool(dl.get("ok"))}
        if not dl.get("ok"):
            record["error"] = dl.get("error_message")
        downloads.append(record)
    return downloads


def _poll_active(store: Store, api_key: str) -> tuple[dict, list[tuple]]:
    """Poll every DISPATCHED task once and advance state only — no downloads.

    Downloading is deliberately deferred (see run_tick): a slow download must
    not delay refilling the concurrency slot the completed task just freed.

    Returns (summary, succeeded), where succeeded is a list of
    (row, results) pairs awaiting download.
    """
    summary = {"succeeded": 0, "failed": 0, "pending": 0, "poll_errors": 0}
    succeeded: list[tuple] = []
    for row in store.get_active():
        result = query_task(api_key, row["rh_task_id"])
        if not result.get("ok"):
            # Poll/network problem only — do NOT terminalize, do NOT resubmit.
            summary["poll_errors"] += 1
            continue
        if not result.get("terminal"):
            store.apply_query_result(row["id"], "PENDING",
                                     rh_status=result.get("rh_status"))
            summary["pending"] += 1
        elif result["status"] == "SUCCESS":
            store.apply_query_result(
                row["id"], "SUCCESS", results=result.get("results"),
                cost_money=result.get("cost_money"),
                cost_third_party_money=result.get("cost_third_party_money"),
                cost_coins=result.get("cost_coins"),
                cost_time_s=result.get("cost_time_s"),
            )
            summary["succeeded"] += 1
            if result.get("results"):
                succeeded.append((row, result["results"]))
        else:
            store.apply_query_result(
                row["id"], "FAILED", error_code=result.get("error_code", ""),
                error_type=result.get("error_type", "UNKNOWN"),
                error_message=result.get("error_message", ""),
            )
            summary["failed"] += 1
    return summary, succeeded


def _download_succeeded(store: Store, succeeded: list[tuple], cfg) -> dict:
    """Download outputs for tasks that reached SUCCESS this tick.

    Best effort: a download failure is recorded on the task but never voids
    its SUCCESS state. Runs after the refill dispatch so replacement jobs can
    already be queued/running on RunningHub while large files download locally.
    """
    stats = {"downloaded": 0, "download_errors": 0}
    for row, results in succeeded:
        downloads = _download_outputs(store, row, results, cfg)
        store.set_downloads(row["id"], downloads)
        stats["downloaded"] += sum(1 for d in downloads if d.get("ok"))
        stats["download_errors"] += sum(1 for d in downloads if not d.get("ok"))
    return stats


# tick single-flight lock lives in notify.py (file-based, worker-scoped).


def run_tick(cfg, api_key: str) -> dict:
    """One non-blocking advance of the pool. Returns a JSON-able summary.

    Four phases, ordered so a freed concurrency slot is refilled within the
    same tick — before any (potentially slow) output download:
      1. dispatch   fill slots already free at tick start
      2. poll       advance states of in-flight tasks (no downloads)
      3. dispatch   refill slots just freed by phase-2 completions
      4. download   fetch outputs; replacement jobs already run on RH meanwhile
    """
    store = Store(cfg.db_path)
    dispatch1 = _dispatch_pending(store, api_key, cfg.concurrency)
    poll, succeeded = _poll_active(store, api_key)
    dispatch2 = _dispatch_pending(store, api_key, cfg.concurrency)
    poll.update(_download_succeeded(store, succeeded, cfg))
    dispatch = {
        "dispatched": dispatch1["dispatched"] + dispatch2["dispatched"],
        "submit_failed": dispatch1["submit_failed"] + dispatch2["submit_failed"],
    }
    return {
        "dispatched": dispatch,
        "polled": poll,
        "counts": store.count_status(),
    }


def cmd_tick(args) -> int:
    cfg = load_config()
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print(json.dumps({"error": "NO_API_KEY"}))
        return 2
    out = run_tick(cfg, api_key)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_reconcile(args) -> int:
    """Force a full poll sync of every DISPATCHED task (post-restart).

    State sync + downloads only — it never dispatches PENDING jobs.
    """
    cfg = load_config()
    store = Store(cfg.db_path)
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print(json.dumps({"error": "NO_API_KEY"}))
        return 2
    poll, succeeded = _poll_active(store, api_key)
    poll.update(_download_succeeded(store, succeeded, cfg))
    print(json.dumps({"reconciled": poll, "counts": store.count_status()},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_workflow(args) -> int:
    """Inspect task-type definitions and validate them against raw exports."""
    if args.wf_command == "list":
        types = workflow_def.load_task_types()
        out = [{
            "typeId": t.typeId, "displayName": t.displayName,
            "workflowId": t.workflowId, "instanceType": t.instanceType,
            "params": [p.name for p in t.params],
        } for t in types]
        print(json.dumps({"types": out}, ensure_ascii=False, indent=2))
        return 0

    if args.wf_command == "info":
        t = workflow_def.get_task_type(args.type_id)
        print(json.dumps({
            "typeId": t.typeId, "version": t.version,
            "displayName": t.displayName, "description": t.description,
            "workflowId": t.workflowId, "instanceType": t.instanceType,
            "params": [vars(p) for p in t.params],
            "fixedOverrides": t.fixedOverrides,
        }, ensure_ascii=False, indent=2))
        return 0

    # validate [typeId]
    reports = ([workflow_def.validate_type(workflow_def.get_task_type(args.type_id))]
               if args.type_id else workflow_def.validate_all())
    payload = [{"typeId": r.typeId, "ok": r.ok,
                "errors": r.errors, "warnings": r.warnings} for r in reports]
    print(json.dumps({"reports": payload}, ensure_ascii=False, indent=2))
    return 0 if all(r.ok for r in reports) else 1


def cmd_status(args) -> int:
    cfg = load_config()
    store = Store(cfg.db_path)
    if args.pool_id is not None or args.rh_task_id:
        row = store.get_task(pool_id=args.pool_id, rh_task_id=args.rh_task_id)
        print(json.dumps(row_to_dict(row) if row else {"error": "NOT_FOUND"},
                         ensure_ascii=False, indent=2))
        return 0 if row else 1
    rows = store.list_tasks(status=args.status_filter, limit=args.limit)
    out = {
        "counts": store.count_status(),
        "tasks": [row_to_dict(r) for r in rows],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _loads(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


# ----------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RunningHub async workflow task pool")
    sub = p.add_subparsers(dest="command", required=True)

    pe = sub.add_parser("enqueue", help="Add workflow job(s)")
    pe.add_argument("--type", help="Task type id from task-types.json")
    pe.add_argument("--param", action="append", help="name=value (repeatable)")
    pe.add_argument("--output", help="Output dir for this job's downloads")
    pe.add_argument("--workflow-id")
    pe.add_argument("--node", action="append", help="nodeId:fieldName=value")
    pe.add_argument("--instance-type", choices=["default", "plus", "ultra"])
    pe.add_argument("--from-file", help="JSON file: job or list of jobs")
    pe.add_argument("--no-notify", action="store_true",
                    help="Do not create the polling automation")

    pt = sub.add_parser("tick", help="One non-blocking advance")
    pt.add_argument("--api-key", "-k")

    pr = sub.add_parser("reconcile", help="Resync active tasks with RH")
    pr.add_argument("--api-key", "-k")

    pw = sub.add_parser("workflow", help="Inspect/validate task-type definitions")
    pw.add_argument("wf_command", choices=["list", "info", "validate"])
    pw.add_argument("type_id", nargs="?")

    ps = sub.add_parser("status", help="Query ledger")
    ps.add_argument("--pool-id", type=int)
    ps.add_argument("--rh-task-id")
    ps.add_argument("--status-filter")
    ps.add_argument("--limit", type=int, default=50)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {
        "enqueue": cmd_enqueue,
        "tick": cmd_tick,
        "reconcile": cmd_reconcile,
        "workflow": cmd_workflow,
        "status": cmd_status,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
