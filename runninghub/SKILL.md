---
name: runninghub
description: "Generate images and videos via RunningHub API. For reliable OpenClaw Web UI execution, use python3 /root/.openclaw/workspace/scripts/runninghub.py. Run immediately when user requests generation; do not ask for API key first."
homepage: https://www.runninghub.cn
metadata:
  {
    "openclaw":
      {
        "emoji": "🎬",
        "requires": { "bins": ["python3", "curl"] },
        "primaryEnv": "RUNNINGHUB_API_KEY",
      },
  }
---

# RunningHub Skill (Reliable)

This skill provides a stable RunningHub workflow for OpenClaw Web UI.

## One-time install (required)

Copy the script to OpenClaw workspace runtime path:

```bash
mkdir -p /root/.openclaw/workspace/scripts
cp /data/RHClaw/runninghub/scripts/runninghub.py /root/.openclaw/workspace/scripts/runninghub.py
chmod +x /root/.openclaw/workspace/scripts/runninghub.py
```

Optional workspace skill copy:

```bash
mkdir -p /root/.openclaw/workspace/skills/runninghub
cp /data/RHClaw/runninghub/SKILL.md /root/.openclaw/workspace/skills/runninghub/SKILL.md
```

## Execution policy

- When user asks to generate/edit media, run `exec` immediately.
- Do not ask user to set/export API key first.
- Do not pass placeholder values like `your_api_key_here`.
- Prefer running without `--api-key` so script fallback can resolve key from config.

## Text-to-Image

```bash
python3 /root/.openclaw/workspace/scripts/runninghub.py --task text-to-image \
  --prompt "a cat astronaut floating in space, 4K cinematic" \
  --resolution 2k --aspect-ratio 16:9 \
  --output /tmp/runninghub-output/space-cat.png
```

## Image-to-Image

```bash
python3 /root/.openclaw/workspace/scripts/runninghub.py --task image-to-image \
  --prompt "change the background to a cyberpunk city at night" \
  --image /tmp/runninghub-output/space-cat.png \
  --resolution 2k \
  --output /tmp/runninghub-output/space-cat-edited.png
```

## Image-to-Video

```bash
python3 /root/.openclaw/workspace/scripts/runninghub.py --task image-to-video \
  --prompt "the cat slowly turns its head and blinks" \
  --image /tmp/runninghub-output/space-cat-edited.png \
  --duration 8 \
  --output /tmp/runninghub-output/space-cat-video.mp4
```

## Notes

- Script prints `MEDIA:/absolute/path` for OpenClaw attachment rendering.
- Key resolution order:
  1) `--api-key` (valid non-placeholder)
  2) `RUNNINGHUB_API_KEY` env
  3) `~/.openclaw/openclaw.json` at `skills.entries.runninghub.env.RUNNINGHUB_API_KEY`
- Video generation is slower; use higher timeout (`>=600s`).
