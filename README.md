# RHClaw — RunningHub Skill for OpenClaw

[English](./README_en.md)

为 [OpenClaw](https://github.com/openclaw/openclaw) 打造的通用多媒体生成技能，由 [RunningHub](https://www.runninghub.cn) API 驱动。

**275 个标准 API 端点 + 无限 AI 应用**，覆盖图片、视频、音频、3D 模型生成、多模态文本理解，以及任意用户创建的 AI 应用（ComfyUI 工作流）。

## 能力一览

| 类别 | 端点数 | 支持任务 |
|------|--------|----------|
| **图片** | 59 | 文生图、图生图、图片放大、Midjourney 风格 |
| **视频** | 166 | 文生视频、图生视频、首尾帧生成、视频续写/编辑、运动控制、多模态视频 |
| **音频** | 16 | 文字转语音、音乐生成、声音克隆 |
| **3D** | 12 | 文字转 3D、图片转 3D、多图转 3D |
| **文本** | 22 | 图片理解、视频理解、文本处理 |
| **AI 应用** | 无限 | 运行任意 RunningHub AI 应用（自定义 ComfyUI 工作流） |

## 快速开始

### 安装

在 OpenClaw 对话中发送：

> 从 https://github.com/HM-RunningHub/OpenClaw_RH_Skills 安装 RunningHub 技能

助手会自动克隆仓库、复制文件到工作区，并引导你完成 API Key 配置。

### 更新

当技能有新版本时，在 OpenClaw 对话中发送：

> 从 https://github.com/HM-RunningHub/OpenClaw_RH_Skills 更新 并重新读取@runninghub/SKILL.md

助手会拉取最新代码并重新加载技能配置，无需重新输入 API Key。

### 前置条件

- **API Key** — 在 [RunningHub API 管理页面](https://www.runninghub.cn/enterprise-api/sharedApi) 创建（点击"新建"）
- **账户余额** — [前往充值](https://www.runninghub.cn/vip-rights/4)，API 调用需要余额

## 使用方式

安装完成后，直接用自然语言跟助手对话即可：

- *"帮我画一只在公园里玩耍的小狗"*
- *"把这张照片做成视频"*
- *"给我的视频配个背景音乐"*
- *"把这张图放大到 4K"*
- *"把这张图转成 3D 模型"*
- *"帮我跑这个 AI 应用 https://www.runninghub.cn/ai-detail/1877265245566922800"*
- *"最热门的 AI 应用有哪些？"*
- *"推荐一些最新的 AI 应用"*

助手会自动选择最合适的 RunningHub 端点来完成你的请求；如果是 AI 应用，则获取应用节点信息、引导你设置参数并运行；还可以浏览推荐、最热、最新的 AI 应用。

### 视频生成交互

生成视频时，助手会展示 8 个精选模型让你选择：

> 1. 🚀 **Google Veo 3.1 Fast** — 又快效果又好，性价比之王
> 2. 🔥 **Grok Video** — Grok 驱动，画面想象力超强
> 3. 🎯 **Kling v3.0 Pro** — 运动自然，拍人物首选
> 4. 🎬 **Google Veo 3.1 Pro** — 电影感拉满
> 5. ✨ **Vidu Q3 Pro** — 风格化独特
> 6. ⭐ **Sora** — Sora 同款引擎
> 7. 🌊 **MiniMax Hailuo** — 速度快画面细腻
> 8. 🌱 **Seedance 2.0** — 效果超赞，最长15秒+自动配音+支持真人，最高4K

选个数字就能开始生成，不选默认用 Google Veo 3.1 Fast。

### 图片生成交互

生成图片时，助手会展示 5 个精选模型让你选择：

> 1. 🎨 **全能图片PRO** — 香蕉Pro同款，默认推荐，综合效果最好
> 2. ⚡ **全能图片V2** — 香蕉2同款，最快最便宜
> 3. 🎭 **悠船 v7** — Midjourney 风格，欧美大片质感
> 4. 🤖 **GPT Image 2** — GPT image2 同款，语义理解强，改图也很稳
> 5. 📷 **Seedream v5** — 字节跳动出品，写实照片感超强

选个数字就能开始生成，不选默认用全能图片PRO。

## 项目结构

```
runninghub/
├── SKILL.md                        # OpenClaw 技能定义（路由表 + 示例 + 交互规则）
├── scripts/
│   ├── runninghub.py               # 标准模型 API 客户端（275 端点）
│   ├── runninghub_app.py           # AI 应用客户端（自定义 ComfyUI 工作流）
│   └── build_capabilities.py       # 从 models_registry.json 生成 capabilities.json
└── data/
    └── capabilities.json           # 完整端点目录（自动生成）
```

## 脚本模式

### 标准模型 API（runninghub.py）

| 模式 | 命令 | 用途 |
|------|------|------|
| **检查** | `--check` | 验证 API Key + 查询余额 |
| **列表** | `--list [--type T] [--task T]` | 浏览可用端点 |
| **详情** | `--info ENDPOINT` | 查看端点参数 |
| **执行** | `--endpoint EP --prompt "..." -o /tmp/out` | 使用指定端点执行 |
| **自动** | `--task TASK --prompt "..." -o /tmp/out` | 自动选择最佳端点 |

### AI 应用（runninghub_app.py）

| 模式 | 命令 | 用途 |
|------|------|------|
| **检查** | `--check` | 验证 API Key + 查询余额 |
| **浏览** | `--list [--sort S] [--size N] [--page N]` | 浏览推荐/最热/最新 AI 应用 |
| **节点** | `--info WEBAPP_ID` | 查看 AI 应用的可修改节点 |
| **执行** | `--run WEBAPP_ID --node ... --file ... -o /tmp/out` | 运行 AI 应用 |

## 更新能力目录

当 RunningHub 上线新的 API 端点时，重新生成目录：

```bash
python3 scripts/build_capabilities.py \
  --registry /path/to/ComfyUI_RH_OpenAPI/models_registry.json \
  --output data/capabilities.json
```

## 许可证

[Apache-2.0](./LICENSE)
