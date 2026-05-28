# agent4kdump

`agent4kdump` 是一个面向 Linux kernel `vmcore` 的智能分析工具。它会把
`kdump-gdbserver`、`gdb`、内核源码检索、已知问题搜索和 LLM Agent 串起来，先判断
crash 是否命中已知 bug，再在需要时进入根因分析。项目同时提供命令行入口和
React + Tauri 桌面客户端。

## 功能概览

- 基于 `vmcore`、`vmlinux` 和 `kdump-gdbserver` 启动调试环境
- 通过 GDB、CodeQuery、源码定位等工具提取 crash 上下文
- 使用 Search Agent 检索 syzbot、CVE、patch、邮件列表等公开信息
- 对未知问题运行 Analyze Agent，输出根因、触发路径、修复建议和关键证据
- 可选启用 RAG / PageIndex，把历史分析经验注入后续分析
- 桌面客户端支持会话管理、配置校验、vmcore 上传、运行分析和报告导出


## 运行环境

推荐在 Linux 或 WSL 中运行分析流程。Windows 可以用于编辑代码和部分前端开发，但真实
`vmcore` 分析依赖 Linux 调试工具链。

必备环境：

- Python 3.13+
- `uv`
- `gdb` 或 `gdb-multiarch`
- `addr2line`
- `cscope`
- `ctags`
- CodeQuery：`cqmakedb`、`cqsearch`
- 可执行的 `kdump-gdbserver`
- Linux 内核源码目录，至少包含 `vmlinux`
- 待分析的 `vmcore`

桌面客户端额外需要：

- Node.js + npm
- Rust + Cargo
- Tauri Linux 系统依赖，例如 WebKitGTK、AppIndicator、OpenSSL、librsvg 等

内核源码建议先在源码根目录执行：

```bash
make V=1 scripts_gdb
```

这会生成/更新 `scripts/gdb/vmlinux-gdb.py` 等 GDB 辅助脚本。

## 安装依赖

1. 克隆项目后进入仓库根目录：

```bash
cd agent4kdump
```

2. 安装 Python 依赖：

```bash
uv sync
```

3. 如果需要运行桌面客户端，安装前端依赖：

```bash
cd client
npm install
cd ..
```

4. 准备 `kdump-gdbserver`。

仓库当前包含 `kdump_analyze/kdump-gdbserver/kdump-gdbserver` 的本地运行路径。
如果需要从源码重新构建，请参考 `kdump_analyze/kdump.md`，准备并编译：

- `libkdumpfile`
- `kdump-gdbserver`
- `pykdumpfile`

运行前可加载本地 kdump 运行库路径：

```bash
source kdump_analyze/env.sh
```

## 配置环境变量

复制模板并填写自己的密钥：

```bash
cp .env.example .env
```

常用字段：

```dotenv
API_KEY=your_llm_api_key
MODEL_NAME=gpt-4o
MODEL_PROVIDER=openai
LLM_BASE_URL=

TAVILY_API_KEY=your_tavily_key

LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

PAGEINDEX_API_KEY=
OPENAI_API_KEY=
OPENAI_API_BASE=
```

说明：

- `API_KEY`、`MODEL_NAME`、`MODEL_PROVIDER`、`LLM_BASE_URL` 用于初始化 LLM
- `TAVILY_API_KEY` 用于 Search Agent 的网页检索
- `LANGFUSE_*` 用于可选追踪
- `PAGEINDEX_API_KEY`、`OPENAI_API_KEY`、`OPENAI_API_BASE` 用于可选 RAG / PageIndex 能力

不要把真实 API Key 写入 README、示例配置或提交记录。

## 配置分析参数

复制配置模板：

```bash
cp config.example.yaml config.yaml
```

示例：

```yaml
linux_path: /path/to/linux
gdb_path: auto
vmcore: /path/to/vmcore
kdump_server: auto
syzbot_data: ./data
enable_rag: false
build_codequery: true
rag_cache_dir: ./cache/rag
kdump_host: 127.0.0.1
kdump_port: 1234
kdump_args: []
```

字段说明：

- `linux_path`：Linux 内核源码根目录，目录下必须有 `vmlinux`
- `gdb_path`：`gdb` 可执行文件路径；`auto` 会从环境变量和 `PATH` 中查找
- `vmcore`：待分析的 crash dump 文件
- `kdump_server`：`kdump-gdbserver` 路径；`auto` 会优先查找仓库内置路径和 `PATH`
- `syzbot_data`：本地 syzbot 数据目录，保留给搜索增强使用
- `enable_rag`：是否启用 RAG / PageIndex
- `build_codequery`：初始化时是否构建 CodeQuery 数据库
- `rag_cache_dir`：RAG 缓存目录
- `kdump_host`、`kdump_port`：本地调试服务地址
- `kdump_args`：传给 `kdump-gdbserver` 的额外参数

## 命令行使用

先做配置校验，不启动调试器：

```bash
uv run python main.py --dry-run
```

使用默认 `config.yaml` 运行完整分析：

```bash
uv run python main.py
```

指定配置文件：

```bash
uv run python main.py --config /path/to/config.yaml
```

打印配置后要求确认：

```bash
uv run python main.py --confirm
```

本次运行跳过 CodeQuery 构建：

```bash
uv run python main.py --no-codequery
```

典型输出包括：

- 配置摘要
- PageIndex / RAG 状态
- Known Bug Search Result
- Root Cause Analysis Result
- `root_cause`、`trigger_path`、`fix_suggestion`、`confidence`
- crash 位置、关键源码位置、证据和验证 TODO

## 桌面客户端使用

开发模式需要同时启动后端 API 和前端页面。

1. 启动本地 API：

```bash
uv run uvicorn client.backend.app:app --host 127.0.0.1 --port 8000
```

2. 启动前端：

```bash
cd client
npm run dev
```

然后访问 Vite 输出的本地地址，通常是 `http://127.0.0.1:5173`。

客户端主要流程：

- 在 Settings 中填写或加载 `.env`
- 创建分析会话
- 填写 `linux_path`、`vmcore`、`gdb_path`、`kdump_server` 等配置
- 点击 Validate 校验配置
- 点击 Run 启动分析
- 查看事件流、结果摘要和 Markdown 报告

vmcore 可以直接填写服务端路径，也可以通过客户端上传。上传文件会保存到：

```text
cache/client_uploads/vmcore/<upload_id>/
```

如果使用 Tauri 桌面模式：

```bash
cd client
npm run desktop:dev
```

Tauri 启动时会优先连接 `127.0.0.1:8000`，如果没有现成 API 服务，会尝试启动打包后的后端；
开发检出环境下也会回退到 `uv run uvicorn client.backend.app:app --host 127.0.0.1 --port 8000`。

## 构建客户端

Linux / WSL 下构建桌面客户端：

```bash
cd client
npm run build:linux
```

或直接执行：

```bash
bash client/scripts/build-linux.sh
```

构建产物会复制到仓库根目录 `dist/`，常见文件包括：

```text
dist/agent4kdump-client-linux-x64
dist/agent4kdump-client-linux-x64.AppImage
dist/agent4kdump-client-linux-x64.deb
```

如果缺少 Tauri Linux 系统依赖，请先按当前发行版安装 WebKitGTK、AppIndicator、OpenSSL、
librsvg 等原生包后再构建。

## 常见检查

运行分析前建议确认：

- `linux_path` 指向正确的内核源码根目录
- `linux_path/vmlinux` 存在
- `linux_path/scripts/gdb/vmlinux-gdb.py` 存在
- `vmcore` 文件存在且当前用户可读
- `gdb`、`addr2line`、`cscope`、`ctags`、`cqmakedb`、`cqsearch` 可执行
- `kdump-gdbserver` 可执行
- `.env` 中已配置可用的 LLM Key
- 需要网页搜索时已配置 `TAVILY_API_KEY`
- 需要 RAG / PageIndex 时已配置对应 API Key，并确认 `enable_rag: true`

## 排错提示

- 报 `Required runtime inputs are missing`：检查 `config.yaml` 中的路径和可执行文件
- 找不到 `gdb`：把 `gdb_path` 改成绝对路径，或确保 `gdb` 在 `PATH` 中
- 找不到 `kdump-gdbserver`：把 `kdump_server` 改成绝对路径，或执行 `source kdump_analyze/env.sh`
- CodeQuery 首次构建慢：这是正常现象；临时跳过可用 `--no-codequery`
- Search Agent 无法联网检索：检查 `TAVILY_API_KEY` 和网络环境
- RAG 初始化失败：先把 `enable_rag` 改为 `false`，确认基础分析流程可运行后再启用

## 参考文档

- `docs/module_design/searchAgent.md`
- `docs/module_design/analyzeAgent.md`
- `docs/module_design/RAG.md`
- `docs/search-analyze-rag-improvement-notes.md`
- `docs/workflow-tree-api-design.md`
- `docs/taint-analysis-tree-design.md`
- `client/README.md`
