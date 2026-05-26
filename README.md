# agent4kdump

## Client Build

Linux client artifacts are built into the repository-root `dist/` directory.
Run this from Linux or WSL:

```bash
./build-linux-wsl.sh
```

If the WSL/Linux host is missing Tauri system packages, run:

```bash
./build-linux-wsl.sh --install-system-deps
```

Expected outputs are `dist/agent4kdump-client-linux-x64`,
`dist/agent4kdump-client-linux-x64.AppImage`, and
`dist/agent4kdump-client-linux-x64.deb`.

## Project Layout For GitHub

Commit the source layout below. Local data, build outputs, dependency folders,
and private config files are ignored.

```text
.
|-- main.py                    # CLI entry point
|-- log.py                     # logging setup
|-- pyproject.toml             # Python project dependencies
|-- config.example.yaml        # safe config template
|-- .env.example               # safe environment template
|-- build.sh                   # backend bundle helper
|-- build-linux-wsl.sh         # Linux/WSL client bundle helper
|-- agent4kdump-backend.spec   # PyInstaller backend spec
|-- client/                    # complete desktop client
|   |-- app/                   # React + Vite UI
|   |-- backend/               # local FastAPI service used by the client
|   |-- shared/                # API contract and shared docs
|   |-- scripts/               # client build scripts
|   `-- src-tauri/             # Tauri desktop shell
|-- docs/                      # design notes and change logs
|-- scripts/                   # legacy helper scripts
`-- src/
    `-- agents/                # agent workflow, tools, RAG, and kdump utils
```

Do not commit `.env` or `config.yaml`. Create local copies from
`.env.example` and `config.example.yaml` when setting up a machine.

`agent4kdump` 是一个面向 Linux kernel `vmcore` 场景的智能分析工具。它把
`kdump-gdbserver`、`gdb`、代码检索工具和 LLM Agent 串起来，先判断崩溃是否属于
已知 bug，再在需要时继续做根因分析，并可选接入 RAG 经验库提升复用能力。

## 主要能力

- 基于 `vmcore` + `vmlinux` 启动 `kdump-gdbserver` 与 `gdb/mi`
- 提取和清洗 crash report，辅助定位调用栈与源码位置
- 使用 Search Agent 检索 syzbot / CVE / patch / 邮件列表等公开信息
- 对未知问题继续执行 Analyze Agent，输出根因、触发路径、修复建议和关键证据
- 可选启用 RAG，把历史分析经验与 Linux 背景知识注入分析流程
- 运行过程中提供结构化终端输出，便于人工复核

## 分析流程

1. 读取 `--config` 指定的配置文件
2. 初始化 `kdump-gdbserver`、`gdb`、内核源码路径和 CodeQuery 数据库
3. 运行 Search Agent，判断当前 crash 是否已知
4. 如果不是已知问题，则运行 Analyze Agent 做根因分析
5. 如果启用了 RAG，则在分析前检索上下文，并在成功后持久化经验

## 目录结构

```text
.
├─ main.py                       # 入口脚本
├─ config.yaml                   # 本地运行配置示例
├─ log.py                        # 日志初始化
├─ scripts/                      # 辅助脚本
├─ docs/                         # 设计文档、改造记录、变更日志
├─ src/
│  └─ agents/                    # Agent 逻辑以及 tools / CodeQuery / WebSearch
│     └─ utils/                  # 模型、kdump / gdb 封装等底层能力
└─ uv.lock                       # 锁定依赖
```

## 运行环境

推荐在 Linux 或 WSL 环境下运行。本项目虽然可以在 Windows 中编辑，但实际分析流程依赖
Linux 调试工具链和 shell 命令。

建议准备以下环境：

- Python 3.13+
- `gdb`
- `addr2line`
- `cscope`
- `ctags`
- `cqmakedb` / `cqsearch`（CodeQuery）
- 可执行的 `kdump-gdbserver`
- 已编译好的 Linux 内核源码目录，至少包含：
  - `vmlinux`
  - `scripts/gdb/vmlinux-gdb.py`
- 待分析的 `vmcore`

## Python 依赖

项目根目录包含 `pyproject.toml` 和 `uv.lock`，建议优先使用 `uv` 安装：

```bash
uv sync
```

如果运行时报缺少包，请补齐当前代码实际依赖的常用库，例如：

- `rich`
- `pyyaml`
- `python-dotenv`
- `requests`
- `beautifulsoup4`

## 配置说明

入口命令默认读取当前目录的 `config.yaml`：

```bash
python main.py
```

如果要使用其它配置文件，再显式传入：

```bash
python main.py --config /path/to/config.yaml
```

`config.yaml` 主要字段：

```yaml
linux_path: ./kernel/linux
gdb_path: auto
vmcore: ./vmcore
kdump_server: auto
syzbot_data: ./data
enable_rag: false
```

字段说明：

- `linux_path`：Linux 内核源码根目录
- `gdb_path`：`gdb` 可执行文件路径，默认走系统 PATH
- `vmcore`：待分析的 crash dump 文件
- `kdump_server`：`kdump-gdbserver` 可执行文件路径
- `syzbot_data`：本地 syzbot 相关数据目录
- `enable_rag`：是否启用经验库 / PageIndex 检索

注意：

- 不要把真实 API Key 写进 `README.md`、仓库示例或提交记录
- 当前代码中的模型配置主要从 `.env` 读取，`config.yaml` 更适合放本地路径类配置
- 如果已有明文密钥文件，建议尽快改为本地私有 `.env`，并避免提交到版本库

## `.env` 环境变量

根据当前代码，常见环境变量如下：

```dotenv
API_KEY=your_llm_api_key
MODEL_NAME=gpt-4o
MODEL_PROVIDER=openai
LLM_BASE_URL=

TAVILY_API_KEY=your_tavily_key

LANGFUSE_SECRET_KEY=your_langfuse_secret
LANGFUSE_PUBLIC_KEY=your_langfuse_public
LANGFUSE_HOST=https://cloud.langfuse.com

PAGEINDEX_API_KEY=
OPENAI_API_KEY=
OPENAI_API_BASE=
```

说明：

- Search Agent 的网页检索依赖 `TAVILY_API_KEY`
- `src/agents/utils/model.py` 中的模型初始化依赖 `API_KEY`、`MODEL_NAME`、`MODEL_PROVIDER`
- Langfuse 追踪默认按必填环境变量初始化，未配置时需要注意启动报错风险
- 启用 PageIndex / RAG 时，可能还需要补充对应 API 配置

## 一次典型运行需要准备什么

在运行 `main.py` 前，请确认：

- `linux_path` 指向正确的内核源码目录
- `linux_path/vmlinux` 存在
- `linux_path/scripts/gdb/vmlinux-gdb.py` 存在
- `vmcore` 文件存在
- `gdb`、`addr2line`、`kdump-gdbserver` 可执行
- 如果需要已知漏洞检索，`.env` 中已配置 `TAVILY_API_KEY`
- 如果需要 LLM 推理，`.env` 中已配置模型相关环境变量

## 输出结果

程序会在终端打印：

- 配置摘要
- RAG / PageIndex 状态
- Known Bug Search Result
- Root Cause Analysis Result

如果 Search Agent 认定为已知问题，输出会包含候选指纹、查询记录、证据和匹配链接。
如果进入根因分析阶段，输出会包含：

- `root_cause`
- `trigger_path`
- `fix_suggestion`
- `confidence`
- `crash_site`
- `key_locations`
- `patch_sketch`

## `scripts/` 目录

- `scripts/start.sh`：使用 QEMU 启动本地内核调试环境
- `scripts/update.sh`：用 `pipreqs` 重新生成依赖清单
- `scripts/requirements.txt`：脚本侧依赖记录
- `scripts/README.md`：脚本目录说明

## `docs/` 目录

`docs/` 下保存了较完整的设计与演进资料，建议优先阅读：

- `docs/module_design/searchAgent.md`
- `docs/module_design/analyzeAgent.md`
- `docs/module_design/RAG.md`
- `docs/search-analyze-rag-improvement-notes.md`
- `docs/workflow-tree-api-design.md`
- `docs/taint-analysis-tree-design.md`

## 已知注意事项

- 这是一个偏研究/工程验证性质的工具，依赖本地环境完整度较高
- CodeQuery 建库阶段会扫描内核源码，首次运行可能较慢
- RAG、PageIndex、Langfuse、Tavily 都属于可选增强能力，但配置不完整时可能影响启动
- 当前项目更适合作为本地分析工作台，而不是开箱即用的通用产品

## 建议的后续整理

如果你准备继续维护这个仓库，建议下一步补齐：

1. `config.example.yaml` 与 `.env.example`
2. 更明确的依赖安装脚本
3. 最小可运行示例目录
4. 常见报错排查说明
