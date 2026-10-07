# Enota13 翻译与字幕技能

本仓库保存个人技能 `cn-subtitle-style`：为英语视频制作英文、中文或中英双语 ASS 字幕，结合本地逐词语音识别、语义划句、全局单调对齐、波形复核，以及个人中文翻译和字幕样式习惯。

## 技能目录

```text
skills/cn-subtitle-style/
├── SKILL.md       # 完整工作流程与约束
├── agents/        # Codex 显示信息
├── scripts/       # 语音识别、划句、样式检查与词汇标红
├── references/    # 中文翻译风格、术语、ASS 样式与时间轴规则
└── assets/        # 常用词与四六级词汇数据
```

## 在 Codex 中安装

向 Codex 发出以下指令：

> 使用 skill-installer 从 https://github.com/Enota13-name/Enota13style_translation 安装 skills/cn-subtitle-style。

也可以把完整的 `cn-subtitle-style` 文件夹放入当前 Codex 的个人技能目录或项目的 `.agents/skills/` 目录，保留内部文件的相对位置。

## 使用

向 Codex 提供英语视频、已有字幕或参考 ASS，并发出指令：

> 使用 $cn-subtitle-style 按我的翻译风格制作字幕。

技能会确认本次是否需要中文，以及中文单语或中英双语的交付方式。中英双语采用中文在上、英文在下；最终会结合源视频分辨率、参考样式和声学证据检查字幕。

仅需翻译风格时，可参考 [中文翻译风格](skills/cn-subtitle-style/references/chinese-style.md) 与 [术语表](skills/cn-subtitle-style/references/glossary.md)。完整字幕流程见 [SKILL.md](skills/cn-subtitle-style/SKILL.md)。

## 本地运行环境

本仓库包含技能、脚本与词汇数据；语音模型、Python 运行环境和 CUDA 库需要在使用机器上另行准备。

- 语音识别脚本使用 `faster-whisper`、`pysubs2`，并用 FFprobe 读取视频信息；需要转换视频格式时另用 FFmpeg。
- `whisper_env.py` 使用 `CODEX_SUBS_LIBS` 指定本地依赖目录，未设置时使用原机器的默认目录。换电脑时请设置这个环境变量。
- 默认模型位置为 `D:\AI\whisper-models\faster-whisper-large-v3`。换位置时使用 `--model` 指定模型目录。
- 语音识别默认使用 CUDA 和 float16；实际设备与计算类型通过脚本参数配置。

例如，在已准备好依赖和模型的 Windows 环境中：

```powershell
$env:CODEX_SUBS_LIBS = 'D:\your-python-libraries'
python .\skills\cn-subtitle-style\scripts\transcribe.py 'D:\videos\source.mp4' --model 'D:\your-whisper-model' --dump-json 'D:\videos\source.words.json'
```

请替换示例路径。该命令只输出识别文本与逐词时间数据；完整字幕还需要划句、可选中文翻译、波形精修和最终检查。环境与参数细节见 [语音识别说明](skills/cn-subtitle-style/references/transcribing.md)。
