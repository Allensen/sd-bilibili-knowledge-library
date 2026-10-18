# 第三方组件与内容

本仓库发布 Skill 的代码、原创说明和阅读模板，不包含第三方模型权重、Python 运行时、用户视频、字幕、Cookie 或账号数据。

首次运行可能根据实际需要从上游下载以下组件。它们仍适用各自的许可；本项目的 MIT 许可不改变上游条款。具体依赖版本与哈希见 [requirements.lock](scripts/requirements.lock)。

| 上游 | 在本项目中的用途 | 官方项目 / 文档 |
| --- | --- | --- |
| uv | 独立 Python 环境与包安装 | [Astral uv](https://github.com/astral-sh/uv) |
| Python standalone builds | 缺少 Python 时准备独立运行时 | [Astral Python builds](https://github.com/astral-sh/python-build-standalone) |
| sherpa-onnx | 本地语音识别推理 | [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) |
| SenseVoice | 按需下载中文语音识别模型 | [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)、[模型下载说明](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html) |
| faster-whisper | 使用随包提供的语音活动检测；不下载 Whisper 权重 | [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) |
| PyAV | 音频解码与按需截帧 | [PyAV](https://github.com/PyAV-Org/PyAV) |

其他运行依赖按各自软件包附带的许可使用。模型下载流程会保留上游 LICENSE。

原视频、字幕与截图的权利属于相应权利人。能访问内容不等于获得公开再分发完整视频或逐字稿的授权。本仓库内的 `docs/demo/` 为原创演示数据，不包含用户收藏或第三方视频的全文。
