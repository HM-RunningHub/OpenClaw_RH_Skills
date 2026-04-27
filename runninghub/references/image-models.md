# Image Model Selection

**Whenever** the user wants ANY image generation (text-to-image OR image-edit/image-to-image), you MUST show this menu and WAIT:

> 好的！先帮你选个图片模型～
>
> 1. 🎨 **全能图片PRO** — 香蕉Pro同款，默认推荐，综合效果最好
> 2. ⚡ **全能图片V2** — 香蕉2同款，最快最便宜
> 3. 🎭 **悠船 v7** — Midjourney 风格，欧美大片质感
> 4. 🤖 **GPT Image 2** — GPT image2 同款，语义理解强，改图也很稳
> 5. 📷 **Seedream v5** — 字节跳动出品，写实照片感超强
>
> 说个数字就行～ 不选的话我默认用 🎨全能图片PRO 哦！

**Do NOT invent your own model list. Do NOT skip this menu. Use EXACTLY this 5-model list.**

After user replies, map choice → endpoint:

**Text-to-image** (no source image):
| # | Endpoint |
|---|----------|
| 1 (default) | `rhart-image-n-pro/text-to-image` |
| 2 | `rhart-image-n-g31-flash/text-to-image` |
| 3 | `youchuan/text-to-image-v7` |
| 4 | `rhart-image-g-2/text-to-image` |
| 5 | `seedream-v5-lite/text-to-image` |

**Image-to-image / Image edit** (user has source image):
| # | Endpoint |
|---|----------|
| 1 (default) | `rhart-image-n-pro/edit` |
| 2 | `rhart-image-n-g31-flash/image-to-image` |
| 3 | `rhart-image-n-pro/edit` ⚠️ 悠船无图生图，回退到全能PRO |
| 4 | `rhart-image-g-2/image-to-image` |
| 5 | `seedream-v5-lite/image-to-image` |

When user picks 悠船 (3) for image-to-image, tell them warmly:
> "悠船模型暂时不支持图生图，我帮你用全能图片PRO来处理哈～ 效果也很棒的！"

## Matching Rules

- Number 1-5 → use that model
- Partial name ("全能", "PRO", "V2") → match to #1 or #2
- "悠船" / "Midjourney" / "MJ" → #3
- "GPT Image" / "GPT image2" / "GPT Image 2" / "G-2" → #4
- "Seedream" / "种子" / "写实" / "照片" → #5
- "随便" / "你选" / "默认" → #1
- "最快的" / "便宜的" → #2
- "效果最好的" → #1

Skip menu ONLY if: user named a specific model, or said "跟上次一样" / "再来一个".

## After Model Is Chosen

Confirm the choice warmly, then ask for missing info if needed:
> "好嘞，用全能图片PRO！有什么画面要求吗？比如风格、尺寸、画质～"

Smart defaults (use these if user doesn't specify):
- Resolution: 2k
- Aspect ratio: 1:1 (square); if user mentions landscape/横版 → 16:9; portrait/竖版 → 9:16

## Prompt Optimization

When the user gives a short/vague prompt, ENHANCE it before sending to the API. Example:
- User says: "画一只猫" → Enhance to: "A fluffy orange tabby cat sitting on a windowsill, warm afternoon sunlight streaming through, soft bokeh background, photorealistic, 4K"
- User says: "赛博朋克城市" → Enhance to: "A neon-lit cyberpunk cityscape at night, towering skyscrapers with holographic billboards, rain-slicked streets reflecting pink and blue lights, cinematic wide-angle shot, 8K ultra-detailed"

Always write prompts in **English** for best model results, even if the user speaks Chinese.

## AI Image Editing (special case)

If the user wants **AI-powered image editing** (e.g. "把背景换成海边", "去掉这个人", "加个帽子"):
- Use `alibaba/qwen-image-2.0-pro/image-edit` directly — no model menu needed for this case.
- This is a different capability from the image generation models above.
