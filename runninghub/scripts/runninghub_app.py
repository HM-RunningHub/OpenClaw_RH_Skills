#!/usr/bin/env python3
"""
RunningHub AI Application client for OpenClaw.

Run any RunningHub AI Application (custom ComfyUI workflow) by webappId.
Uses only Python stdlib and curl.

Modes:
  --check                          Account health check (key + balance)
  --list [--sort S] [--size N]     Browse AI applications
  --info WEBAPP_ID                 Show app's modifiable nodes
  --run WEBAPP_ID [options]        Execute an AI application task
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

API_HOST = f"https://{os.environ.get('RUNNINGHUB_DOMAIN', 'www.runninghub.ai')}"
APP_LIST_PATH = "/openapi/v2/aiapp/list"
NODE_INFO_PATH = "/api/webapp/apiCallDemo"
UPLOAD_PATH = "/task/openapi/upload"
SUBMIT_PATH = "/task/openapi/ai-app/run"

SCRIPT_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPT_DIR))
from runninghub import resolve_api_key, require_api_key, cmd_check, poll_task, fix_mov_to_mp4  # noqa: E402


# ---------------------------------------------------------------------------
# HTTP helpers (curl-based, stdlib only)
# ---------------------------------------------------------------------------

def curl_get(url: str, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["curl", "-s", "-S", "--fail-with-body", "--max-time", str(timeout), url]
    return subprocess.run(cmd, capture_output=True, text=True)


def curl_post_json(url: str, payload: dict, timeout: int = 60) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        tmp_path = f.name
    try:
        cmd = [
            "curl", "-s", "-S", "--fail-with-body", "-X", "POST", url,
            "--max-time", str(timeout),
            "-H", "Content-Type: application/json",
            "-H", f"Host: {API_HOST.split('//')[1]}",
            "-d", f"@{tmp_path}",
        ]
        return subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(tmp_path)


def curl_upload(url: str, api_key: str, file_path: str, timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = [
        "curl", "-s", "-S", "--fail-with-body", "-X", "POST", url,
        "--max-time", str(timeout),
        "-H", f"Host: {API_HOST.split('//')[1]}",
        "-F", f"apiKey={api_key}",
        "-F", "fileType=input",
        "-F", f"file=@{file_path}",
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _parse_response(result: subprocess.CompletedProcess, context: str) -> dict:
    body = result.stdout or result.stderr
    if result.returncode != 0:
        try:
            err = json.loads(body)
            msg = err.get("msg", body)
        except (json.JSONDecodeError, TypeError):
            msg = body
        print(json.dumps({
            "error": "API_ERROR",
            "message": f"{context} failed: {msg}",
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(json.dumps({
            "error": "API_ERROR",
            "message": f"{context}: invalid JSON response: {result.stdout[:500]}",
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# AI Application API functions
# ---------------------------------------------------------------------------

def _extract_webapp_id(invoke_example: str) -> str | None:
    """Extract webappId from the invokeExample cURL string."""
    m = re.search(r'/run/ai-app/(\d+)', invoke_example)
    return m.group(1) if m else None


def list_apps(api_key: str, sort: str = "RECOMMEND", size: int = 10,
              page: int = 1, days: int = 7) -> dict:
    url = f"{API_HOST}{APP_LIST_PATH}"
    payload: dict = {"current": page, "size": min(size, 50), "sort": sort}
    if sort == "HOTTEST" and days:
        payload["days"] = days

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        tmp_path = f.name
    try:
        cmd = [
            "curl", "-s", "-S", "--fail-with-body", "-X", "POST", url,
            "--max-time", "60",
            "-H", "Content-Type: application/json",
            "-H", f"Authorization: {api_key}",
            "-d", f"@{tmp_path}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(tmp_path)

    resp = _parse_response(result, "List AI apps")

    if resp.get("code") != 0:
        print(json.dumps({
            "error": "LIST_FAILED",
            "message": resp.get("msg", "Failed to list AI apps"),
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    return resp.get("data", {})


def get_node_info(api_key: str, webapp_id: str) -> list[dict]:
    url = f"{API_HOST}{NODE_INFO_PATH}?apiKey={api_key}&webappId={webapp_id}"
    result = curl_get(url)
    resp = _parse_response(result, "Get node info")

    if resp.get("code") != 0:
        print(json.dumps({
            "error": "APP_INFO_FAILED",
            "message": resp.get("msg", "Failed to get AI app info"),
            "detail": resp,
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    node_list = resp.get("data", {}).get("nodeInfoList", [])
    if not node_list:
        print(json.dumps({
            "error": "NO_NODES",
            "message": "No modifiable nodes found for this AI app. "
                       "Make sure the app has been run at least once on the web.",
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    return node_list


def upload_file(api_key: str, file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    url = f"{API_HOST}{UPLOAD_PATH}"
    print(f"Uploading {path.name}...", file=sys.stderr)
    result = curl_upload(url, api_key, file_path)
    resp = _parse_response(result, "Upload file")

    if resp.get("code") != 0 or resp.get("msg") != "success":
        print(json.dumps({
            "error": "UPLOAD_FAILED",
            "message": f"Upload failed: {resp.get('msg', resp)}",
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    file_name = resp.get("data", {}).get("fileName")
    if not file_name:
        print(json.dumps({
            "error": "UPLOAD_FAILED",
            "message": "Upload succeeded but no fileName returned",
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    print(f"Uploaded: {file_name}", file=sys.stderr)
    return file_name


def submit_task(api_key: str, webapp_id: str, node_info_list: list[dict],
                instance_type: str = "default") -> dict:
    url = f"{API_HOST}{SUBMIT_PATH}"
    payload = {
        "apiKey": api_key,
        "webappId": int(webapp_id),
        "nodeInfoList": node_info_list,
    }
    if instance_type and instance_type != "default":
        payload["instanceType"] = instance_type

    print(f"Submitting AI app task (webapp {webapp_id})...", file=sys.stderr)
    result = curl_post_json(url, payload)
    resp = _parse_response(result, "Submit task")

    if resp.get("code") != 0:
        print(json.dumps({
            "error": "SUBMIT_FAILED",
            "message": f"Submit failed: {resp.get('msg', resp)}",
            "detail": resp,
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    data = resp.get("data", {})
    task_id = data.get("taskId")
    if not task_id:
        print(json.dumps({
            "error": "SUBMIT_FAILED",
            "message": "No taskId in response",
            "detail": resp,
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    prompt_tips_str = data.get("promptTips")
    if prompt_tips_str:
        try:
            tips = json.loads(prompt_tips_str)
            node_errors = tips.get("node_errors", {})
            if node_errors:
                print(json.dumps({
                    "error": "NODE_ERRORS",
                    "message": "Workflow has node errors",
                    "node_errors": node_errors,
                }, ensure_ascii=False), file=sys.stderr)
                sys.exit(1)
        except (json.JSONDecodeError, TypeError):
            pass

    return data


def download_file(url: str, output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["curl", "-s", "-S", "-L", "-o", output_path, "--max-time", "300", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Download failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return str(Path(output_path).resolve())


# ---------------------------------------------------------------------------
# --node / --file argument parsing
# ---------------------------------------------------------------------------

def parse_node_arg(arg: str) -> tuple[str, str, str]:
    """Parse 'nodeId:fieldName=value' into (nodeId, fieldName, value)."""
    colon_idx = arg.find(":")
    if colon_idx == -1:
        print(f"Error: invalid --node format '{arg}', expected nodeId:fieldName=value", file=sys.stderr)
        sys.exit(1)
    node_id = arg[:colon_idx]
    rest = arg[colon_idx + 1:]
    eq_idx = rest.find("=")
    if eq_idx == -1:
        print(f"Error: invalid --node format '{arg}', expected nodeId:fieldName=value", file=sys.stderr)
        sys.exit(1)
    field_name = rest[:eq_idx]
    field_value = rest[eq_idx + 1:]
    return node_id, field_name, field_value


def apply_modifications(api_key: str, node_list: list[dict],
                        node_args: list[str] | None,
                        file_args: list[str] | None) -> list[dict]:
    if node_args:
        for arg in node_args:
            nid, fname, fval = parse_node_arg(arg)
            target = next(
                (n for n in node_list if n["nodeId"] == nid and n["fieldName"] == fname),
                None,
            )
            if target:
                target["fieldValue"] = fval
            else:
                node_list.append({"nodeId": nid, "fieldName": fname, "fieldValue": fval})

    if file_args:
        for arg in file_args:
            nid, fname, fpath = parse_node_arg(arg)
            uploaded_name = upload_file(api_key, fpath)
            target = next(
                (n for n in node_list if n["nodeId"] == nid and n["fieldName"] == fname),
                None,
            )
            if target:
                target["fieldValue"] = uploaded_name
            else:
                node_list.append({"nodeId": nid, "fieldName": fname, "fieldValue": uploaded_name})

    return node_list


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _download_cover(url: str, out_path: str) -> bool:
    """Download a cover image. Returns True on success."""
    if not url:
        return False
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["curl", "-s", "-S", "-L", "-o", out_path, "--max-time", "15", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0 and Path(out_path).exists() and Path(out_path).stat().st_size > 0


def cmd_list(api_key: str, sort: str, size: int, page: int, days: int):
    data = list_apps(api_key, sort, size, page, days)
    records = data.get("records", [])

    cover_dir = Path("/tmp/openclaw/rh-output/app_covers")
    cover_dir.mkdir(parents=True, exist_ok=True)

    apps = []
    for i, r in enumerate(records):
        webapp_id = _extract_webapp_id(r.get("invokeExample", ""))
        cover_url = r.get("cover", "")

        app: dict = {
            "title": r.get("title", ""),
            "description": r.get("description", ""),
        }
        if webapp_id:
            app["webappId"] = webapp_id

        if cover_url:
            ext = cover_url.split("?")[0].rsplit(".", 1)[-1].lower() if "." in cover_url.split("/")[-1] else "jpg"
            if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
                ext = "jpg"
            cover_path = str(cover_dir / f"cover_{sort.lower()}_p{page}_{i+1}.{ext}")
            if _download_cover(cover_url, cover_path):
                app["coverFile"] = str(Path(cover_path).resolve())
            else:
                print(f"Warning: failed to download cover for '{app['title']}'", file=sys.stderr)

        apps.append(app)

    output = {
        "sort": sort,
        "page": int(data.get("current", page)),
        "size": int(data.get("size", size)),
        "total": int(data.get("total", 0)),
        "pages": int(data.get("pages", 0)),
        "hasNext": data.get("hasNext", False),
        "apps": apps,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


def cmd_info(api_key: str, webapp_id: str):
    node_list = get_node_info(api_key, webapp_id)
    print(json.dumps({
        "webappId": webapp_id,
        "nodeCount": len(node_list),
        "nodes": node_list,
    }, indent=2, ensure_ascii=False))


def cmd_run(args):
    api_key = require_api_key(args.api_key)
    webapp_id = args.run

    node_list = get_node_info(api_key, webapp_id)
    node_list = apply_modifications(api_key, node_list, args.node, args.file)

    data = submit_task(api_key, webapp_id, node_list, args.instance_type or "default")
    task_id = str(data["taskId"])

    final = poll_task(api_key, task_id)
    results = final.get("results")

    usage = final.get("usage") or {}
    consume_money = usage.get("consumeMoney") or usage.get("thirdPartyConsumeMoney")
    task_cost_time = usage.get("taskCostTime")

    if not results:
        print(json.dumps({
            "error": "TASK_FAILED",
            "message": "No results in final response",
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    file_urls = []
    for item in results:
        url = item.get("url") or item.get("outputUrl")
        ext = item.get("outputType", "")
        if url:
            file_urls.append((url, ext))

    if not file_urls:
        text_results = []
        for item in results:
            t = item.get("text") or item.get("content") or item.get("output")
            if t:
                text_results.append(t)
        if text_results:
            for t in text_results:
                print(t)
            if consume_money is not None:
                print(f"COST:¥{consume_money}")
            return
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    output_base = args.output
    for i, (url, ext) in enumerate(file_urls):
        if not ext:
            ext = _guess_ext_from_url(url)
        if output_base:
            if len(file_urls) == 1:
                out_path = output_base
            else:
                stem = Path(output_base).stem
                suffix = Path(output_base).suffix or f".{ext}"
                out_path = str(Path(output_base).parent / f"{stem}_{i+1}{suffix}")
        else:
            out_path = f"/tmp/openclaw/rh-output/app_result_{i+1}.{ext}"

        if ext:
            out_path = str(Path(out_path).with_suffix(f".{ext}"))
        elif not Path(out_path).suffix:
            out_path = f"{out_path}.png"

        print(f"Downloading result {i+1}/{len(file_urls)}...", file=sys.stderr)
        full_path = download_file(url, out_path)
        fix_mov_to_mp4(full_path)
        print(f"OUTPUT_FILE:{full_path}")

    if consume_money is not None:
        print(f"COST:¥{consume_money}")
    if task_cost_time and str(task_cost_time) != "0":
        print(f"DURATION:{task_cost_time}s")


def _guess_ext_from_url(url: str) -> str:
    path = url.split("?")[0]
    if "." in path.split("/")[-1]:
        return path.split("/")[-1].rsplit(".", 1)[-1].lower()
    return "png"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RunningHub AI Application client for OpenClaw",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Modes:
  --check                           Check API key and account balance
  --list [--sort S] [--size N]      Browse AI applications
  --info WEBAPP_ID                  Show app's modifiable nodes
  --run WEBAPP_ID [options]         Execute an AI application task

Examples:
  python3 runninghub_app.py --check
  python3 runninghub_app.py --list --sort HOTTEST --size 5
  python3 runninghub_app.py --list --sort NEWEST
  python3 runninghub_app.py --info 1877265245566922800
  python3 runninghub_app.py --run 1877265245566922800 \\
    --node "52:prompt=a girl dancing" \\
    --file "39:image=/tmp/photo.jpg" \\
    -o /tmp/result.png
""",
    )

    parser.add_argument("--check", action="store_true", help="Check API key and account status")
    parser.add_argument("--list", action="store_true", help="Browse AI applications")
    parser.add_argument("--sort", choices=["RECOMMEND", "HOTTEST", "NEWEST"], default="RECOMMEND",
                        help="Sort order for --list (default: RECOMMEND)")
    parser.add_argument("--size", type=int, default=10,
                        help="Number of results per page for --list (default: 10, max: 50)")
    parser.add_argument("--page", type=int, default=1,
                        help="Page number for --list (default: 1)")
    parser.add_argument("--days", type=int, default=7,
                        help="Hotness window in days for --list --sort HOTTEST (default: 7)")
    parser.add_argument("--info", metavar="WEBAPP_ID", help="Show modifiable nodes for an AI app")
    parser.add_argument("--run", metavar="WEBAPP_ID", help="Run an AI application")
    parser.add_argument("--node", action="append",
                        help="Set node value as nodeId:fieldName=value (repeatable)")
    parser.add_argument("--file", action="append",
                        help="Upload file and set node as nodeId:fieldName=/path (repeatable)")
    parser.add_argument("--instance-type", choices=["default", "plus"], default="default",
                        help="GPU instance type: default=24G, plus=48G (default: default)")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--api-key", "-k", help="API key (optional, resolved from config)")

    args = parser.parse_args()

    if args.check:
        cmd_check(args.api_key)
    elif args.list:
        api_key = require_api_key(args.api_key)
        cmd_list(api_key, args.sort, args.size, args.page, args.days)
    elif args.info:
        api_key = require_api_key(args.api_key)
        cmd_info(api_key, args.info)
    elif args.run:
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
