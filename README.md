# 短视频脚本 Agent

第 4 题。输入产品主题、受众、平台、时长和风格，输出带素材引用的分镜脚本。脚本超时或出现不合适的表述时，Agent 读取检查结果，改稿后再检查。

## 先看什么

- [真实模型运行记录](examples/codex/summary.json)：正常生成、缺少时长、没有素材、工具失败、超时改稿。
- [超时改稿全过程](examples/codex/over_duration/result.json)：每个版本的旁白、时长、问题和下一步动作。
- [生成后的分镜稿](examples/codex/normal/script.md)：可以直接阅读和修改。
- [测试与结果](docs/03-evaluation.md)。

## 运行

Python 3.11 及以上。项目使用标准库，无需安装 Python 依赖。在仓库根目录执行：

```bash
python -m src.cli --input examples/mock/normal/input.json --provider mock --output runs/demo
python -m unittest discover -s tests -v
```

结果写入 `runs/demo/`：`script.md` 是分镜稿，`result.json` 包含全部版本，`trace.jsonl` 每行记录一步。任务完成时退出码为 0，需要补充信息或未完成时为 2。

### 使用真实模型

本次验证用 Codex CLI 0.165.0-alpha.1.2、`gpt-6.1-sol`。先安装 [Codex CLI](https://developers.openai.com/codex/cli/)，完成 `codex login`，再执行：

```bash
python -m src.cli --input examples/codex/normal/input.json --provider codex --output runs/live
python -m src.cli --input examples/codex/over_duration/input.json --provider codex --output runs/revision
```

每轮调用一次模型，默认最多 8 轮。CLI 使用已有登录，不需要把密钥写进项目。`--model` 可以指定账号可用的其他模型。

也可以使用兼容 Chat Completions 的接口。设置 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 后，将 `--provider` 改为 `openai`。变量格式见 [.env.example](.env.example)，程序从系统环境读取，不自动加载 `.env`。

### 复现异常

```bash
# 首次脚本检查失败，让模型读取错误后决定下一步
python -m src.cli --input examples/codex/tool_failure/input.json --provider codex --fail-once check_script --output runs/failure

# 一次跑完离线用例
python evaluate.py

# 重跑本次五组真实模型用例，会调用模型
python evaluate.py --provider codex --cases normal missing_info no_material tool_failure over_duration
```

`mock` 是确定性的离线测试入口，用来检查工具和状态流转；模型决策的实际记录放在 `examples/codex/`。

## 项目结构

```text
src/             Agent 循环、模型接入、素材检索与脚本检查
tests/           可执行测试
data/            合成产品资料和品牌规则
examples/        输入、实际输出、逐步记录、测试结果
docs/            需求、设计、评估、AI 使用记录、复盘
evaluate.py      批量运行用例并生成记录
```

示例使用合成产品“轻剪”的四条功能资料。模型选择内容、安排画面和节奏，旁白通过事实 ID 对应素材原文。

详细说明：[需求](docs/01-requirements.md) · [方案](docs/02-solution.md) · [评估](docs/03-evaluation.md) · [AI 使用](docs/04-ai-usage.md) · [复盘](docs/05-retrospective.md)
