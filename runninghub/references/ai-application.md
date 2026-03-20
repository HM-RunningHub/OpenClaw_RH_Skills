# AI Application

**Use `runninghub_app.py`** (NOT `runninghub.py`) for AI app tasks. AI apps are user-created ComfyUI workflows hosted on RunningHub.

## When to Trigger

Trigger AI Application flow when the user:
- Mentions "AI应用", "AI app", "工作流", "workflow", "webappId"
- Pastes a RunningHub AI app link like `runninghub.ai/ai-detail/1877265245566922800`
- Says "帮我跑这个应用", "运行这个工作流", "用这个 AI 应用处理"
- Asks about available apps: "有什么AI应用", "最热门的应用", "最新的应用", "推荐什么应用"

## Browse AI Apps

When the user wants to discover or explore AI apps, use `--list`:

```bash
# Recommended apps (default)
python3 {baseDir}/scripts/runninghub_app.py --list --sort RECOMMEND --size 10

# Hottest apps in the last 7 days
python3 {baseDir}/scripts/runninghub_app.py --list --sort HOTTEST --size 10 --days 7

# Newest apps
python3 {baseDir}/scripts/runninghub_app.py --list --sort NEWEST --size 10

# Page 2
python3 {baseDir}/scripts/runninghub_app.py --list --sort RECOMMEND --size 10 --page 2
```

The output is JSON with an `apps` array. Each app has: `title`, `description`, `webappId`, and `coverFile` (local path to downloaded cover image).

**Present apps to the user with cover images**. For EACH app, use the `message` tool to send its cover image, then describe it:

```
For each app in the list:
  1. Call message tool: { "action": "send", "text": "1. 全能图片2.0 — 多功能图片生成", "media": "/tmp/openclaw/rh-output/app_covers/cover_xxx.png" }
  2. Move to next app
After all apps, send a final message:
  { "action": "send", "text": "想试试哪个？告诉我编号就行！也可以说'下一页'看更多～" }
```

Alternatively, if sending many images is too slow, you can send just the **first 3 covers** via `message` tool and list the rest as text.

Rules:
- ALWAYS send cover images via `message` tool — NEVER show cover URLs or file paths as text
- Show title as bold, description if available
- NEVER show raw webappId to the user
- If `coverFile` is missing for an app (download failed), just show the title as text
- If the user picks one, proceed to Step 1 (get webappId) using the selected app's webappId
- For "翻页" / "下一页" / "更多", call `--list` with `--page 2`, etc.
- Map user intents: "推荐" → RECOMMEND, "最热/热门" → HOTTEST, "最新/新的" → NEWEST

## Step 1 — Get webappId

If the user provides a link, extract the number from the URL:
- `https://www.runninghub.ai/ai-detail/1877265245566922800` → webappId = `1877265245566922800`

If the user selected an app from the list, use its `webappId` directly.

If no webappId and no list selection, ask warmly:
> "好的！要用 AI 应用的话，发给我应用链接或者 webappId 就行～ 在应用页面的地址栏可以找到哦！或者我帮你看看有什么推荐的应用？"

## Step 2 — Fetch node info

```bash
python3 {baseDir}/scripts/runninghub_app.py --info WEBAPP_ID
```

This returns a JSON with all modifiable nodes, each containing:
- `nodeId` — node identifier
- `nodeName` — node type (e.g. "LoadImage", "RH_Translator")
- `fieldName` — field key (e.g. "prompt", "image", "model")
- `fieldValue` — current default value
- `fieldType` — value type: `STRING`, `IMAGE`, `AUDIO`, `VIDEO`, `LIST`, `INT`, `FLOAT`, `BOOLEAN`
- `description` — Chinese description of the field

## Step 3 — Present nodes to user

Show the modifiable nodes in a friendly format. Example:

> 这个 AI 应用有以下可修改的参数：
>
> 1. 📷 **上传图像** (节点 39) — 当前: 默认示例图
> 2. ✏️ **图像编辑文本输入框** (节点 52) — 当前: "给这个女人的发型变成齐耳短发"
> 3. 🔄 **模型切换** (节点 37) — 当前: flux-kontext-pro
> 4. 📐 **输出比例** (节点 37) — 当前: match_input_image
>
> 你想修改哪些？直接告诉我就行～ 比如 "换张图片" 或 "把提示词改成xxx"

Rules:
- Use `description` as the label (not fieldName)
- For IMAGE/AUDIO/VIDEO type, show 📷/🔊/🎬 icon and hint "上传文件"
- For LIST type with `fieldData`, mention available options
- For STRING type, show current value in quotes
- NEVER show raw nodeId/fieldName to the user — translate to friendly Chinese

## Step 4 — Notify user, then execute

**Before running the script**, ALWAYS send a progress notification via `message` tool:
> "好的，开始运行 AI 应用啦！工作流生成通常需要几分钟，请稍等～ 🎬"

This is critical — AI app tasks are slow, and users need to know the task has started. Send the notification FIRST, then execute the script.

Map user's modifications to `--node` and `--file` arguments:

```bash
# Modify text node + upload image
python3 {baseDir}/scripts/runninghub_app.py --run WEBAPP_ID \
  --node "52:prompt=make her hair into a short bob cut" \
  --file "39:image=/tmp/openclaw/rh-output/photo.jpg" \
  -o /tmp/openclaw/rh-output/app_result_$(date +%s).png

# Text-only modification
python3 {baseDir}/scripts/runninghub_app.py --run WEBAPP_ID \
  --node "52:prompt=a boy with sunglasses" \
  -o /tmp/openclaw/rh-output/app_result_$(date +%s).png
```

For GPU-intensive apps, the user can request a larger instance:
- `--instance-type plus` — 48G VRAM (tell user: "用更强的 GPU 跑，可能会快一些但也贵一些")
- Default is `default` (24G VRAM)

## Step 5 — Deliver results

Same rules as standard API: use `message` tool, report cost, suggest next steps.

If the app outputs multiple files, deliver all of them.

## AI App Script Reference

```bash
# Get modifiable nodes for an AI app
python3 {baseDir}/scripts/runninghub_app.py --info 1877265245566922800

# Run AI app with text modification
python3 {baseDir}/scripts/runninghub_app.py --run 1877265245566922800 \
  --node "52:prompt=a boy with sunglasses" \
  -o /tmp/openclaw/rh-output/app_$(date +%s).png

# Run AI app with file upload + text modification
python3 {baseDir}/scripts/runninghub_app.py --run 1877265245566922800 \
  --file "39:image=/tmp/openclaw/rh-output/photo.jpg" \
  --node "52:prompt=change hairstyle to short bob" \
  -o /tmp/openclaw/rh-output/app_$(date +%s).png

# Run on a larger GPU instance
python3 {baseDir}/scripts/runninghub_app.py --run 1877265245566922800 \
  --node "52:prompt=a girl dancing" \
  --instance-type plus \
  -o /tmp/openclaw/rh-output/app_$(date +%s).png
```

Flags: `--node nodeId:fieldName=value`, `--file nodeId:fieldName=/path`, `--instance-type default|plus`, `-o path`
Browse: `--list [--sort RECOMMEND|HOTTEST|NEWEST] [--size N] [--page N] [--days N]`
Discovery: `--info WEBAPP_ID`

## AI App Errors

| Error | Action |
|-------|--------|
| `APP_INFO_FAILED` | webappId wrong or app not publicly accessible → "这个应用 ID 可能不对，确认一下？" |
| `NO_NODES` | App never run on web → "这个应用需要先在网页上成功跑一次才能通过 API 调用哦～" |
| `NODE_ERRORS` | Workflow node errors → "工作流有节点出错了，可能参数不对，要不要看看错误信息？" |
| `TASK_FAILED` | Runtime failure → show friendly error, offer to retry |
| `UPLOAD_FAILED` | File upload failed → "文件上传失败了，再试一次？" |

## Notes

- The AI app must have been run successfully at least once on the RunningHub web interface before it can be called via API.
- Upload links are valid for one day only.
- For prompts in AI apps, keep the user's original language unless the node description suggests otherwise.
- AI app tasks may take 1-10+ minutes depending on the workflow complexity.
