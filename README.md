# RHClaw Skills

This repository stores production-ready OpenClaw skills.

Current skill:
- `runninghub/` - RunningHub image/video generation skill for OpenClaw Web UI.

Quick start:

1. Copy script to OpenClaw workspace runtime:
   - `mkdir -p /root/.openclaw/workspace/scripts`
   - `cp /data/RHClaw/runninghub/scripts/runninghub.py /root/.openclaw/workspace/scripts/runninghub.py`
2. Copy skill file:
   - `mkdir -p /root/.openclaw/workspace/skills/runninghub`
   - `cp /data/RHClaw/runninghub/SKILL.md /root/.openclaw/workspace/skills/runninghub/SKILL.md`
3. Ensure API key exists in:
   - `~/.openclaw/openclaw.json`
   - `skills.entries.runninghub.env.RUNNINGHUB_API_KEY`
