#!/usr/bin/env python3
"""
Domain patcher for RunningHub OpenClaw Skills.

Detects and replaces hardcoded RunningHub domain references across
the entire skill directory. Useful for switching between China mainland
(www.runninghub.cn) and international (www.runninghub.ai) endpoints.

Usage:
  # Preview changes (dry-run, default):
  python3 patch_domain.py

  # Preview switching to China mainland:
  python3 patch_domain.py --to cn

  # Apply changes:
  python3 patch_domain.py --apply

  # Apply switch to international:
  python3 patch_domain.py --to ai --apply

Environment:
  Set RUNNINGHUB_DOMAIN=www.runninghub.cn (or .ai) to control runtime
  API endpoints in runninghub.py / runninghub_app.py without patching files.
  This script patches the static references in docs and fallback defaults.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

DOMAIN_CN = "www.runninghub.cn"
DOMAIN_AI = "www.runninghub.ai"

# Also handle bare domain without www
BARE_CN = "runninghub.cn"
BARE_AI = "runninghub.ai"

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}
TARGET_EXTS = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".sh", ".txt"}


def find_files(root: Path) -> list[Path]:
    """Find all text files that might contain domain references."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            p = Path(dirpath) / fname
            if p.suffix in TARGET_EXTS:
                files.append(p)
    return sorted(files)


def scan_and_replace(
    root: Path,
    from_domain: str,
    to_domain: str,
    from_bare: str,
    to_bare: str,
    apply: bool = False,
) -> list[dict]:
    """Scan files and optionally apply domain replacements."""
    results = []
    files = find_files(root)

    for fpath in files:
        try:
            content = fpath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if from_domain not in content and from_bare not in content:
            continue

        lines = content.split("\n")
        matches = []
        for i, line in enumerate(lines, 1):
            if from_domain in line or from_bare in line:
                matches.append({"line": i, "text": line.rstrip()})

        rel_path = str(fpath.relative_to(root))
        entry = {"file": rel_path, "matches": matches, "count": len(matches)}

        if apply:
            new_content = content.replace(from_domain, to_domain)
            new_content = new_content.replace(from_bare, to_bare)
            # Preserve comment references to the other domain
            # e.g., "set RUNNINGHUB_DOMAIN=www.runninghub.cn" in a comment
            fpath.write_text(new_content, encoding="utf-8")
            entry["patched"] = True

        results.append(entry)

    return results


def detect_current(root: Path) -> str:
    """Detect which domain the repo currently uses (majority wins)."""
    cn_count = 0
    ai_count = 0
    for fpath in find_files(root):
        try:
            content = fpath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        cn_count += content.count(DOMAIN_CN)
        ai_count += content.count(DOMAIN_AI)
    if cn_count > ai_count:
        return "cn"
    elif ai_count > cn_count:
        return "ai"
    return "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="Patch RunningHub domain references (cn ↔ ai)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--to",
        choices=["cn", "ai"],
        default=None,
        help="Target domain: 'ai' for international (runninghub.ai), 'cn' for China (runninghub.cn). "
             "Default: auto-detect current and switch to the other.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually modify files. Without this flag, only shows what would change (dry-run).",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Root directory to scan. Default: auto-detect from script location.",
    )
    args = parser.parse_args()

    # Determine root directory (the skill repo root)
    if args.root:
        root = Path(args.root).resolve()
    else:
        # Script is at runninghub/scripts/patch_domain.py → repo root is ../../
        root = Path(__file__).resolve().parent.parent.parent

    if not root.exists():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        sys.exit(1)

    current = detect_current(root)
    print(f"📍 Current domain: {DOMAIN_CN if current == 'cn' else DOMAIN_AI if current == 'ai' else 'mixed/unknown'}")

    # Determine direction
    if args.to:
        target = args.to
    else:
        target = "ai" if current == "cn" else "cn"

    if target == "ai":
        from_domain, to_domain = DOMAIN_CN, DOMAIN_AI
        from_bare, to_bare = BARE_CN, BARE_AI
    else:
        from_domain, to_domain = DOMAIN_AI, DOMAIN_CN
        from_bare, to_bare = BARE_AI, BARE_CN

    print(f"🔄 Direction: {from_domain} → {to_domain}")
    print(f"{'🔧 MODE: APPLY' if args.apply else '👀 MODE: DRY-RUN (use --apply to modify files)'}\n")

    results = scan_and_replace(root, from_domain, to_domain, from_bare, to_bare, apply=args.apply)

    if not results:
        print(f"✅ No references to {from_domain} found. Nothing to do.")
        return

    total = 0
    for entry in results:
        status = "✅ patched" if entry.get("patched") else "📋 would patch"
        print(f"  {status} {entry['file']} ({entry['count']} occurrences)")
        for m in entry["matches"]:
            print(f"    L{m['line']}: {m['text'][:120]}")
        total += entry["count"]

    print(f"\n{'✅ Patched' if args.apply else '📋 Would patch'}: {total} occurrences in {len(results)} files")

    if not args.apply:
        print(f"\n💡 Run with --apply to modify files:")
        print(f"   python3 {Path(__file__).name} --to {target} --apply")
    else:
        print(f"\n💡 Runtime override (no file changes needed):")
        print(f"   export RUNNINGHUB_DOMAIN={to_domain}")


if __name__ == "__main__":
    main()
