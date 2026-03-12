#!/usr/bin/env python3
"""
RunningHub API client for OpenClaw.

Supports text-to-image, image-to-image, image-to-video, text-to-video.
Uses only Python stdlib and curl.
"""

import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE_URL = "https://www.runninghub.cn/openapi/v2"

TASK_ENDPOINTS = {
    "text-to-image": "/rhart-image-n-pro/text-to-image",
    "image-to-image": "/rhart-image-n-pro/edit",
    "image-to-video": "/rhart-video-s-official/image-to-video",
    "text-to-video": "/rhart-video-s-official/text-to-video",
}

POLL_ENDPOINT = "/query"
UPLOAD_ENDPOINT = "/media/upload/binary"

MAX_POLL_SECONDS = 900
POLL_INTERVAL = 5


def read_key_from_openclaw_config() -> str | None:
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    if not cfg_path.exists():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = (
        cfg.get("skills", {})
        .get("entries", {})
        .get("runninghub", {})
        .get("env", {})
        .get("RUNNINGHUB_API_KEY")
    )
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def get_api_key(provided_key: str | None) -> str:
    if provided_key:
        normalized = provided_key.strip()
        placeholders = {
            "your_api_key_here",
            "<your_api_key>",
            "YOUR_API_KEY",
            "RUNNINGHUB_API_KEY",
        }
        # LLMs may output placeholders. Ignore and fallback.
        if normalized and normalized not in placeholders:
            return normalized

    env_key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
    if env_key:
        return env_key

    cfg_key = read_key_from_openclaw_config()
    if cfg_key:
        return cfg_key

    print(
        "Error: No API key. Set RUNNINGHUB_API_KEY, configure skills.entries.runninghub.env.RUNNINGHUB_API_KEY in ~/.openclaw/openclaw.json, or use --api-key.",
        file=sys.stderr,
    )
    sys.exit(1)


def api_post_json(api_key: str, url: str, payload: dict) -> dict:
    # Use temp JSON file to avoid argument length issues on large payloads.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        tmp_path = f.name
    try:
        cmd = [
            "curl",
            "-s",
            "-S",
            "--fail-with-body",
            "-X",
            "POST",
            url,
            "-H",
            "Content-Type: application/json",
            "-H",
            f"Authorization: Bearer {api_key}",
            "-d",
            f"@{tmp_path}",
            "--max-time",
            "60",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(tmp_path)

    if result.returncode != 0:
        print(f"API request failed: {result.stderr}", file=sys.stderr)
        if result.stdout:
            print(f"Response body: {result.stdout}", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Invalid JSON response: {result.stdout[:500]}", file=sys.stderr)
        sys.exit(1)


def upload_file(api_key: str, file_path: str) -> str:
    url = f"{BASE_URL}{UPLOAD_ENDPOINT}"
    cmd = [
        "curl",
        "-s",
        "-S",
        "--fail-with-body",
        "-X",
        "POST",
        url,
        "-H",
        f"Authorization: Bearer {api_key}",
        "-F",
        f"file=@{file_path}",
        "--max-time",
        "120",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Upload failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    try:
        resp = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Upload returned invalid JSON: {result.stdout[:500]}", file=sys.stderr)
        sys.exit(1)

    if resp.get("code") == 0:
        return resp["data"]["download_url"]

    print(f"Upload error: {resp}", file=sys.stderr)
    sys.exit(1)


def image_to_data_uri(file_path: str) -> str:
    mime_type = mimetypes.guess_type(file_path)[0] or "image/png"
    with open(file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()
    return f"data:{mime_type};base64,{encoded}"


def resolve_image(api_key: str, image_arg: str, force_upload: bool = False) -> str:
    if image_arg.startswith(("http://", "https://")):
        return image_arg

    path = Path(image_arg)
    if not path.exists():
        print(f"Error: file not found: {image_arg}", file=sys.stderr)
        sys.exit(1)

    size = path.stat().st_size
    if force_upload or size > 5 * 1024 * 1024:
        return upload_file(api_key, image_arg)
    return image_to_data_uri(image_arg)


def poll_task(api_key: str, task_id: str) -> dict:
    url = f"{BASE_URL}{POLL_ENDPOINT}"
    print(f"Task ID: {task_id}")
    print("Waiting for result", end="", flush=True)

    elapsed = 0
    while elapsed < MAX_POLL_SECONDS:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        resp = api_post_json(api_key, url, {"taskId": task_id})
        status = resp.get("status", "UNKNOWN")

        if status == "SUCCESS":
            print(f" done ({elapsed}s)")
            return resp
        if status == "FAILED":
            error_msg = resp.get("errorMessage", "Unknown error")
            error_code = resp.get("errorCode", "")
            print(f"\nTask failed: [{error_code}] {error_msg}", file=sys.stderr)
            sys.exit(1)

        print(".", end="", flush=True)

    print(f"\nTimeout after {MAX_POLL_SECONDS}s", file=sys.stderr)
    sys.exit(1)


def download_file(url: str, output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["curl", "-s", "-S", "-L", "-o", output_path, "--max-time", "300", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Download failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return str(Path(output_path).resolve())


def build_payload(args, api_key: str) -> dict:
    payload: dict = {"prompt": args.prompt}

    if args.task == "text-to-image":
        payload["resolution"] = args.resolution or "2k"
        if args.aspect_ratio:
            payload["aspectRatio"] = args.aspect_ratio

    elif args.task == "image-to-image":
        if not args.image:
            print("Error: --image required for image-to-image", file=sys.stderr)
            sys.exit(1)
        payload["imageUrls"] = [resolve_image(api_key, i) for i in args.image]
        payload["resolution"] = args.resolution or "2k"
        if args.aspect_ratio:
            payload["aspectRatio"] = args.aspect_ratio

    elif args.task == "image-to-video":
        if not args.image:
            print("Error: --image required for image-to-video", file=sys.stderr)
            sys.exit(1)
        payload["imageUrl"] = resolve_image(api_key, args.image[0], force_upload=True)
        payload["duration"] = args.duration or "4"

    elif args.task == "text-to-video":
        payload["duration"] = args.duration or "4"
        payload["size"] = args.size or "1280x720"

    return payload


def main():
    parser = argparse.ArgumentParser(description="RunningHub API client")
    parser.add_argument(
        "--task",
        "-t",
        required=True,
        choices=["text-to-image", "image-to-image", "image-to-video", "text-to-video"],
    )
    parser.add_argument("--prompt", "-p", required=True)
    parser.add_argument("--image", "-i", action="append", help="Input image (path or URL, repeatable)")
    parser.add_argument("--resolution", "-r", choices=["1k", "2k", "4k"])
    parser.add_argument("--aspect-ratio", "-a")
    parser.add_argument("--duration", "-d", choices=["4", "8", "12"])
    parser.add_argument("--size", "-s", choices=["720x1280", "1280x720"])
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument("--api-key", "-k")

    args = parser.parse_args()
    api_key = get_api_key(args.api_key)

    submit_url = f"{BASE_URL}{TASK_ENDPOINTS[args.task]}"
    payload = build_payload(args, api_key)

    print(f"Submitting {args.task} task...")
    resp = api_post_json(api_key, submit_url, payload)
    task_id = resp.get("taskId")
    if not task_id:
        print(f"Error: no taskId in response: {json.dumps(resp, ensure_ascii=False)}", file=sys.stderr)
        sys.exit(1)

    final = resp if (resp.get("status") == "SUCCESS" and resp.get("results")) else poll_task(api_key, task_id)
    results = final.get("results")
    if not results:
        print("Error: no results in final response", file=sys.stderr)
        sys.exit(1)

    result = results[0]
    result_url = result.get("url")
    output_type = result.get("outputType", "")
    if not result_url:
        text_result = result.get("text")
        if text_result:
            print(f"Text result: {text_result}")
            return
        print("Error: no URL in results", file=sys.stderr)
        sys.exit(1)

    output_path = args.output
    if output_type:
        output_path = str(Path(args.output).with_suffix(f".{output_type}"))

    print(f"Downloading {output_type or 'file'} result...")
    full_path = download_file(result_url, output_path)
    print(f"\nSaved: {full_path}")
    print(f"MEDIA:{full_path}")


if __name__ == "__main__":
    main()
