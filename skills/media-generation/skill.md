---
name: media-generation
description: "生成图片（media.generate_image）与语音合成（media.generate_tts），走可插拔的 OpenAI 兼容 provider，产物落工作区并回读校验。视频只留接口、不实现。当用户说“画一张图”“生成一张封面”“把这段文字转成音频”时使用。两次生成都要先经过用户的审批卡；没有凭证时显式报未配置。"
version: 0.1.0
allowed-tools:
  - media.generate_image
  - media.generate_tts
source: local
---

# 多媒体生成（图片 / 语音合成）

## 适用场景

- 用户要一张图：配图、封面、示意图、头像 → `media.generate_image`。
- 用户要把文字转成音频：播报、配音、有声片段 → `media.generate_tts`。

## 工具

| 动作 | 输入 | 产物 |
| --- | --- | --- |
| `media.generate_image` | `prompt`（必填，≤4000 字）、`output_name`（必填，纯文件名）、`output_dir`（不传用挂载目录）、`size`（256x256 / 512x512 / 1024x1024 / 1792x1024 / 1024x1792，默认 1024x1024）、`format`（png / jpeg / webp，默认 png） | .png/.jpg/.webp，生成后回读校验（格式魔数 + PNG 尺寸） |
| `media.generate_tts` | `text`（必填，≤4096 字）、`output_name`（必填）、`output_dir`、`voice`（默认 alloy）、`format`（mp3 / wav / opus / aac / flac / pcm，默认 mp3） | 音频文件，生成后回读校验（容器魔数；wav 做结构检查） |

`output_name` 是纯文件名（如 `封面.png`，不带路径也可以，缺后缀会自动补）；`output_dir` 不传就用挂载时配好的目录。

## 步骤

1. 按用户要的产物选动作，把需求整理成输入参数。
2. 调用动作。第一次调用会弹出审批卡——等用户点了“允许”再继续；被拒绝就停下，不要换个名字重传。
3. 成功返回里带 `verification`：`expected` 是生成时报的格式/尺寸，`observed` 是回读看到的，两边对得上才算交付。
4. 把文件路径和校验结果告诉用户。

## 硬规则（先说清楚）

- **两次生成都要审批卡。** 被拒绝就停；不要改参数重交碰运气。
- **没有凭证 = 显式“未配置”。** provider 的 API 凭证走 ZN 凭证存储（引用如 `provider:openai-media`），部署时由用户授权一次。没有配好时，动作会显式报错“未配置”，不会假装生成了什么。
- **视频不做。** provider 接口里留了 `generate_video`，但 R9 只留接口与文档、没有实现。用户要视频时如实说现在做不了，不要拿图片序列凑数冒充视频。
- 文件名带 `../`、后缀不对、目标目录不存在都会显式报错，不要绕过去。

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “审批被拒只是这次没通过，换个 size 再交一次也许就过了。” | 拒绝针对的是这次生成意图本身。改条件重交前，先跟用户确认要改什么。 |
| “没有凭证，我先用 mock 生成一张顶上。” | mock 只用于测试。给用户交付时必须说明真实 provider 未配置，而不是悄悄塞一张假图。 |
| “verification 里格式对不上，但文件能打开，就这样吧。” | 格式对不上说明生成或回读有一边错了，必须查清再交付，不能“差不多”。 |
| “用户要 10 秒短视频，我先生成 10 张图拼成 gif。” | gif 不是视频，也不是用户要的东西。如实说视频未实现，把需求记下来。 |

## References

- 实现与校验逻辑：`runtime/python/zn_agent/core/media_generation_connector.py`（`MockMediaGenerationProvider` / `OpenAICompatibleMediaProvider`，`write_image` / `write_tts_audio`，`verify_image_bytes` / `verify_audio_bytes`，`attach_media_generation_tools`，`register_media_generation_runtime`）。
- 测试：`tests/zn_agent/core/test_media_generation_connector.py`（mock 端到端、坏参数显式失败、未配置显式报错、视频未实现、审批拒绝/允许、重放拒绝、skill evals）。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R9 条目。
