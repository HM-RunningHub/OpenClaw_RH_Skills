# API Key Setup

## Check Status

Run `--check` first:
```bash
python3 {baseDir}/scripts/runninghub.py --check
```

React by `status`:
- `"ready"` → "账号就绪！余额 ¥{balance}，想做点什么？生图、视频、配音都可以找我～"
- `"no_key"` → Guide: 1) 注册 runninghub.ai 2) 创建 Key 3) 充值 4) 发 Key 给我
- `"no_balance"` → "余额空了～ 充个值就能继续：https://www.runninghub.ai/vip-rights/4"
- `"invalid_key"` → "Key 不太对，去这里看看：https://www.runninghub.ai/enterprise-api/sharedApi"

## Save Key

When user sends a key, verify with `--check --api-key THE_KEY`. If valid, save it:

```bash
python3 -c "
import json, pathlib
p = pathlib.Path.home() / '.openclaw' / 'openclaw.json'
p.parent.mkdir(exist_ok=True)
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg.setdefault('skills', {}).setdefault('entries', {}).setdefault('runninghub', {})['apiKey'] = 'THE_KEY'
p.write_text(json.dumps(cfg, indent=2))
"
```

Replace `THE_KEY` with the actual key. OpenClaw auto-injects it as `RUNNINGHUB_API_KEY` env var via `primaryEnv`.
