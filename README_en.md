# RHClaw — RunningHub Skill for OpenClaw

[中文](./README.md)

An [OpenClaw](https://github.com/openclaw/openclaw) skill that brings multimedia generation capabilities — including image, video, audio, 3D, and text — to conversational AI, powered by 294 [RunningHub](https://www.runninghub.cn) API endpoints. Built with zero external dependencies (pure Python 3 + curl), it lets users create rich media content through natural language, with support for both standard model APIs and custom ComfyUI workflows (AI Applications).

## Capabilities

| Category | Endpoints | Tasks |
|----------|-----------|-------|
| **Image** | 67 | text-to-image, image-to-image, image upscale, Midjourney-style |
| **Video** | 171 | text-to-video, image-to-video, start-end frames, video extend/edit, motion control, multimodal video |
| **Audio** | 16 | text-to-speech, music generation, voice clone |
| **3D** | 14 | text-to-3D, image-to-3D, multi-image-to-3D |
| **Text** | 26 | image-to-text, video-to-text, text-to-text |
| **AI Apps** | Unlimited | Run any RunningHub AI Application (custom ComfyUI workflow) |

## Quick Start

### Install

In your OpenClaw chat, say:

> Install the RunningHub skill from https://github.com/HM-RunningHub/OpenClaw_RH_Skills

The assistant will clone the repo, copy files to the workspace, and guide you through API key setup.

### Update

When a new version is available, say in your OpenClaw chat:

> Update from https://github.com/HM-RunningHub/OpenClaw_RH_Skills and re-read @runninghub/SKILL.md

The assistant will pull the latest code and reload the skill config. No need to re-enter your API key.

### Prerequisites

- **API Key** — Get one from [RunningHub API Management](https://www.runninghub.cn/enterprise-api/sharedApi) (click "新建")
- **Wallet balance** — [Recharge here](https://www.runninghub.cn/vip-rights/4) — API calls require funds

## Usage

Once installed, just talk to your OpenClaw assistant in natural language:

- *"Generate a picture of a dog playing in the park"*
- *"Turn this photo into a video"*
- *"Create background music for my video"*
- *"Upscale this image to 4K"*
- *"Convert this image to a 3D model"*
- *"Run this AI app: https://www.runninghub.cn/ai-detail/1877265245566922800"*
- *"What are the hottest AI apps?"*
- *"Show me the newest AI apps"*

The assistant automatically selects the best RunningHub endpoint based on your request. For AI Apps, it fetches the app's node info, guides you through parameter setup, and runs the workflow. You can also browse recommended, hottest, and newest AI apps.

### Video Model Selection

When generating video, the assistant presents 8 curated models to choose from:

> 1. 🚀 **Google Veo 3.1 Fast** — Fast with great quality, best value
> 2. 🔥 **Grok Video** — Grok-powered, incredible imagination
> 3. 🎯 **Kling v3.0 Pro** — Natural motion, best for people
> 4. 🎬 **Google Veo 3.1 Pro** — Cinematic quality
> 5. ✨ **Vidu Q3 Pro** — Unique stylized look
> 6. ⭐ **Sora** — Sora-class engine
> 7. 🌊 **MiniMax Hailuo** — Fast with fine details
> 8. 🌱 **Seedance 2.0** — Top quality, up to 15s + auto audio + real people, up to 4K

Pick a number to start, or the default (Google Veo 3.1 Fast) is used automatically.

### Image Model Selection

When generating images, the assistant presents 5 curated models to choose from:

> 1. 🎨 **RH Image PRO** — Best overall quality, recommended default
> 2. ⚡ **RH Image V2** — Fastest and most affordable
> 3. 🎭 **Youchuan v7** — Midjourney-style, cinematic look
> 4. 🤖 **GPT Image 2** — Strong prompt understanding and reliable image editing
> 5. 📷 **Seedream v5** — ByteDance, strong photorealistic feel

Pick a number to start, or the default (RH Image PRO) is used automatically.

## Architecture

```
runninghub/
├── SKILL.md                        # OpenClaw skill definition (routing table + examples)
├── scripts/
│   ├── runninghub.py               # Standard model API client (294 endpoints)
│   ├── runninghub_app.py           # AI Application client (custom ComfyUI workflows)
│   └── build_capabilities.py       # Generates capabilities.json from models_registry.json
└── data/
    └── capabilities.json           # Full endpoint catalog (auto-generated)
```

## Script Modes

### Standard Model API (runninghub.py)

| Mode | Command | Purpose |
|------|---------|---------|
| **Check** | `--check` | Verify API key + check wallet balance |
| **List** | `--list [--type T] [--task T]` | Browse available endpoints |
| **Info** | `--info ENDPOINT` | View endpoint parameters |
| **Execute** | `--endpoint EP --prompt "..." -o /tmp/out` | Run with specific endpoint |
| **Auto** | `--task TASK --prompt "..." -o /tmp/out` | Auto-select best endpoint |

### AI Application (runninghub_app.py)

| Mode | Command | Purpose |
|------|---------|---------|
| **Check** | `--check` | Verify API key + check wallet balance |
| **Browse** | `--list [--sort S] [--size N] [--page N]` | Browse recommended/hottest/newest AI apps |
| **Nodes** | `--info WEBAPP_ID` | Show modifiable nodes for an AI app |
| **Execute** | `--run WEBAPP_ID --node ... --file ... -o /tmp/out` | Run an AI application |

## Updating Capabilities

When RunningHub adds new API endpoints, regenerate the catalog:

```bash
python3 scripts/build_capabilities.py \
  --registry /path/to/ComfyUI_RH_OpenAPI/models_registry.json \
  --output data/capabilities.json
```

## License

[Apache-2.0](./LICENSE)
