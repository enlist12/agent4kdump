# /client 完整客户端技术栈计划

## 1. 目标

本计划用于指导后续在仓库根目录新增 `/client`，实现一个完整 Windows 客户端，而不是只生成静态 Web 页面或单纯的 WebView 壳。

客户端目标：

- 交付一个可运行的 Windows `.exe`。
- 复用已有 `src/frontend` 的工作站布局设计语言。
- 客户端内置或自动托管本地后端服务，用户不需要手动启动 `uvicorn`。
- 后端继续复用当前 Python 分析能力，不在前端或桌面壳中重写 kdump / gdb / Agent 逻辑。
- UI 核心仍保持 Web-first，后续可以作为网页部署或嵌入其他系统。

## 2. 推荐总体架构

采用三层结构：

```text
/client
├── app/              # React Web UI
├── desktop/          # Tauri 桌面壳
├── backend/          # 客户端本地 API 服务封装
├── shared/           # 前后端共享类型、常量和构建脚本
└── scripts/          # 打包、复制 Python 后端、健康检查脚本
```

运行时结构：

```text
agent4kdump-client.exe
    ├── Tauri WebView
    ├── bundled React UI
    └── local Python API service
            └── existing agent4kdump analysis modules
```

核心原则：

- Tauri 负责窗口、文件选择、进程管理和本机能力。
- React 负责全部业务 UI。
- Python FastAPI 负责分析任务 API、SSE 事件流、session 管理。
- 原有 `src/agents` 仍是唯一分析逻辑来源。

## 3. 技术栈

### 3.1 桌面壳

推荐：

- Tauri v2
- Rust stable
- WebView2 runtime
- NSIS installer

职责：

- 加载打包后的 React 静态资源。
- 启动、停止和监控本地 Python API 服务。
- 分配本地 API 端口。
- 提供文件 / 目录选择能力。
- 打开报告目录、外部链接和日志目录。
- 在退出客户端时清理后端子进程。

不推荐 Electron：

- 当前客户端主要是工程工具，Tauri 体积更小。
- 后端已有 Python 进程，避免再引入大型 Node 桌面运行时。
- Windows 原生安装包体积更可控。

### 3.2 前端 UI

推荐：

- React
- TypeScript
- Vite
- Tailwind CSS
- lucide-react
- TanStack Query
- Zustand
- React Hook Form
- Zod
- React Flow
- Monaco Editor
- TanStack Virtual
- Playwright

沿用 `src/frontend` 的布局风格：

- 左侧窄导航栏。
- 中间主工作区。
- Session Detail 使用 Tab 切换：
  - Root Cause
  - Taint Tree
  - RAG Context
  - Source Code
  - Logs
- 左侧阶段进度栏。
- 右侧上下文 / 证据面板。
- 底部状态条。

UI 设计约束：

- 不做营销页。
- 不做大面积装饰。
- 不出现页面级滚动条，使用面板内部滚动。
- 工具界面保持高信息密度、低干扰、可复核。
- 所有重要结论必须能追溯到证据、日志、源码位置或查询记录。

### 3.3 本地后端服务

推荐：

- FastAPI
- Uvicorn
- Pydantic
- SQLite
- SSE
- Background thread / subprocess task runner
- Python 3.13

职责：

- 创建和管理分析 session。
- 校验 `config.yaml` 和用户输入路径。
- 启动已有 `init_analysis()` / `run_full_analysis()`。
- 推送实时事件流。
- 保存报告、日志、配置快照和结果 JSON。
- 统一暴露 Source Viewer 所需源码读取 API。

后端打包方式有两种：

1. **Phase 1：客户端启动本机 Python 环境**
   - Tauri 启动命令：
     `uv run uvicorn client.backend.app:app --host 127.0.0.1 --port <port>`
   - 优点：开发快，复用现有依赖管理。
   - 缺点：用户机器需要 Python / uv / 项目环境。

2. **Phase 2：PyInstaller 打包后端服务**
   - 将 FastAPI 本地服务打包为 `agent4kdump-backend.exe`。
   - Tauri 启动内置 backend exe。
   - 优点：用户只安装一个客户端，不需要手工准备 Python 服务。
   - 缺点：打包体积更大，gdb / kdump / Linux 工具链仍需要目标环境。

完整客户端应以 Phase 2 为目标。

### 3.4 进程管理

Tauri 需要提供本地进程管理能力：

- 启动后端：
  - 查找空闲端口。
  - 启动 `agent4kdump-backend.exe` 或 `uvicorn`。
  - 等待 `/api/health` 成功。
  - 将 API base URL 注入前端。

- 停止后端：
  - 客户端退出时终止子进程。
  - 异常退出时记录日志。
  - 后端启动失败时展示可操作错误。

- 日志：
  - `client/logs/backend.out.log`
  - `client/logs/backend.err.log`
  - `client/logs/desktop.log`

### 3.5 打包工具链

推荐：

- 前端构建：Vite
- 桌面打包：Tauri CLI
- Python 后端打包：PyInstaller
- Windows 安装器：NSIS
- 构建编排：PowerShell 脚本 + npm scripts

目标产物：

```text
client/dist/
├── agent4kdump-client.exe                 # 免安装主程序
└── agent4kdump-client_0.1.0_x64-setup.exe # Windows 安装器
```

后续也可以补：

- `portable.zip`
- `msi`
- 自动更新包

## 4. /client 目录规划

建议新目录如下：

```text
client/
├── README.md
├── package.json
├── app/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── styles.css
│       ├── api/
│       ├── components/
│       ├── features/
│       ├── pages/
│       ├── platform/
│       └── stores/
├── backend/
│   ├── app.py
│   ├── schemas.py
│   ├── session_store.py
│   ├── runner.py
│   └── source_api.py
├── desktop/
│   ├── Cargo.toml
│   ├── build.rs
│   ├── tauri.conf.json
│   ├── icons/
│   └── src/
│       ├── main.rs
│       ├── backend_process.rs
│       └── commands.rs
├── shared/
│   ├── api-contract.md
│   └── openapi/
└── scripts/
    ├── build-web.ps1
    ├── build-backend.ps1
    ├── build-desktop.ps1
    └── build-all.ps1
```

说明：

- `/client/app` 从 `src/frontend` 迁移或复制第一版 UI。
- `/client/backend` 从 `src/backend` 迁移并补齐完整客户端能力。
- `/client/desktop` 不应包含业务 UI，只包含桌面壳和本机命令。
- `/client/scripts` 负责一键构建完整 `.exe`。

## 5. 前后端 API 计划

必须支持的 API：

```http
GET  /api/health
GET  /api/sessions
POST /api/sessions
GET  /api/sessions/{session_id}
POST /api/sessions/{session_id}/validate
POST /api/sessions/{session_id}/run
POST /api/sessions/{session_id}/cancel
GET  /api/sessions/{session_id}/events
GET  /api/sessions/{session_id}/report
GET  /api/sessions/{session_id}/source
GET  /api/sessions/{session_id}/source/line
```

客户端本地增强 API：

```http
GET  /api/local/runtime
GET  /api/local/logs
POST /api/local/open-path
POST /api/local/reveal-path
```

Tauri 命令：

```text
pick_file
pick_directory
open_external
open_log_dir
backend_status
restart_backend
```

## 6. 数据存储

客户端本地数据建议放在应用数据目录：

```text
%APPDATA%/agent4kdump-client/
├── config.json
├── sessions.db
├── sessions/
│   └── <session_id>/
│       ├── config.yaml
│       ├── result.json
│       ├── report.md
│       └── events.jsonl
└── logs/
```

SQLite 表：

- `sessions`
- `events`
- `reports`
- `recent_paths`
- `settings`

v1 可以先用文件 + JSONL，后续再升级 SQLite。完整客户端建议直接使用 SQLite。

## 7. 安全边界

客户端虽然运行在本机，但仍要保持边界：

- 前端不保存 LLM API Key。
- 后端读取 `.env` 或本机配置，不向 UI 返回密钥。
- Source API 只能读取 session 绑定的 `linux_path`。
- 文件选择只负责填入路径，真实校验由后端完成。
- Tauri allowlist 只开放必要能力。
- 不允许前端执行任意 shell 命令。
- 所有后端子进程命令必须固定模板，参数做白名单校验。

## 8. 构建计划

### Phase 1：/client Web UI 迁移

目标：

- 新增 `/client/app`。
- 迁移 `src/frontend` 已有布局和组件。
- API client 能连接 `/client/backend`。
- 保留 mock fallback。

验收：

- `npm run build:web` 成功。
- 页面布局与 `src/frontend` 一致或更完整。

### Phase 2：/client Backend

目标：

- 新增 `/client/backend`。
- 复用当前 `main.py` 和 `src/agents`。
- 提供 session、run、events、report、source API。

验收：

- `python -m client.backend.app` 或 `uvicorn client.backend.app:app` 可运行。
- 前端能通过本地 API 创建和运行 session。

### Phase 3：Tauri 完整客户端

目标：

- 新增 `/client/desktop`。
- Tauri 启动时自动启动本地 API。
- 前端不再要求用户手动启动后端。

验收：

- 双击 exe 能打开 UI。
- UI 状态条显示 API connected。
- 退出客户端能关闭后端子进程。

### Phase 4：后端打包

目标：

- 使用 PyInstaller 打包 `agent4kdump-backend.exe`。
- Tauri bundle 内包含 backend exe。
- 安装器安装后即可启动完整客户端。

验收：

- 新机器安装后可以打开客户端。
- 不需要手动运行 `uvicorn`。
- 缺少 gdb / vmcore / kernel path 时显示明确错误。

### Phase 5：发布产物

目标：

- `agent4kdump-client.exe`
- `agent4kdump-client_0.1.0_x64-setup.exe`
- `portable.zip`

验收：

- 产物在 `client/dist` 下统一输出。
- README 说明运行前置条件和常见错误。

## 9. 推荐 npm scripts

```json
{
  "scripts": {
    "dev": "concurrently \"npm:dev:backend\" \"npm:dev:app\"",
    "dev:app": "vite --config app/vite.config.ts",
    "dev:backend": "uv run uvicorn client.backend.app:app --host 127.0.0.1 --port 8000",
    "build:web": "vite build --config app/vite.config.ts",
    "build:backend": "powershell -ExecutionPolicy Bypass -File scripts/build-backend.ps1",
    "build:desktop": "tauri build --config desktop/tauri.conf.json",
    "build:all": "powershell -ExecutionPolicy Bypass -File scripts/build-all.ps1"
  }
}
```

## 10. 技术决策结论

完整 `/client` 不应只是 `src/frontend` 的 Tauri 包装。它应该是一个包含 UI、桌面壳、本地 API 服务、进程管理和打包脚本的完整客户端工程。

推荐最终技术组合：

- UI：React + TypeScript + Vite + Tailwind + lucide-react
- 工作台状态：TanStack Query + Zustand
- 图形分析：React Flow
- 代码查看：Monaco Editor
- 桌面壳：Tauri
- 本地 API：FastAPI + Uvicorn + Pydantic
- 本地存储：SQLite
- 后端打包：PyInstaller
- Windows 安装器：NSIS

这套方案可以保留 Web 复用能力，同时满足用户对“一份完整 exe 客户端”的预期。
