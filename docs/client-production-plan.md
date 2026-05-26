# 客户端制作计划

## 1. 目标与边界

本计划面向 `agent4kdump` 的客户端建设。当前项目以 Python CLI 为主，入口位于 `main.py`，分析流程由 `init_analysis()`、`run_full_analysis()`、Search Agent、Analyze Agent、RAG 和 taint tree 组成。客户端不应直接重写分析逻辑，而应作为同一套分析能力的图形化工作台。

核心目标：

- 提供可视化的 kdump 分析工作台，降低配置、运行、复核和归档成本。
- 前端优先按 Web 应用设计，确保后续可以直接部署到浏览器。
- 桌面客户端只作为 Web 前端的运行壳或平台适配层，不分叉业务 UI。
- 支持长任务状态、实时日志、阶段结果、taint tree、RAG 证据和最终报告展示。
- 保持后端分析流程仍由 Python 项目承担，避免在客户端复制 kernel / gdb / LLM Agent 逻辑。

不在 v1 范围内：

- 不做多人协作权限系统。
- 不做云端 vmcore 托管平台。
- 不在浏览器中直接运行 `gdb`、`kdump-gdbserver` 或 CodeQuery。
- 不在前端保存真实 API Key、模型密钥或 Langfuse 密钥。

## 2. 客户端形态

推荐采用一套 Web-first 前端核心，派生两种交付形态：

1. 浏览器 Web 版
   - 通过 `frontend` 构建出的静态资源部署到 Nginx、Caddy 或任意静态站点服务。
   - 浏览器通过 HTTP / WebSocket / SSE 调用后端 API。
   - 适合远程 Linux 分析机、实验室共享服务器、CI 归档服务。

2. 桌面客户端版
   - 使用 Tauri 作为桌面壳，加载同一套 Web 前端。
   - 桌面壳只负责本机能力适配，例如选择本地路径、启动本地 API 服务、读取本地配置。
   - 适合单机工作站或 WSL / Linux 主机上的本地分析场景。

关键约束：

- UI、路由、状态管理、组件和 API SDK 必须完全复用。
- 平台差异只允许进入 `platform adapter` 层，例如 `browserAdapter` 和 `desktopAdapter`。
- 不允许在业务组件中直接调用 Tauri API、Node API 或浏览器私有文件 API。

## 3. 推荐技术栈

### 3.1 前端核心

- 语言：TypeScript
- 构建工具：Vite
- UI 框架：React
- 路由：TanStack Router 或 React Router
- 服务端状态：TanStack Query
- 本地 UI 状态：Zustand
- 表单：React Hook Form + Zod
- 图形可视化：React Flow
- 编辑器 / 代码查看：Monaco Editor
- 日志虚拟列表：TanStack Virtual
- 图标：lucide-react
- 样式：Tailwind CSS + CSS variables
- 组件基础：Radix UI 或 shadcn/ui 风格组件
- 测试：Vitest + Testing Library + Playwright
- 代码质量：ESLint + Prettier + TypeScript strict mode

选型理由：

- React 适合组件化构建复杂工作台界面。
- Vite 适合轻量前端项目和静态资源构建，输出可以直接被浏览器部署和桌面壳加载。
- TanStack Query 适合管理分析任务、轮询、缓存、失败重试和长任务状态。
- React Flow 适合展示 taint tree、调用链、阶段流转等图结构。
- Monaco Editor 适合展示源码片段、patch sketch、日志和报告内容。

官方参考：

- React: <https://react.dev/>
- Vite: <https://vite.dev/>
- TanStack Query: <https://tanstack.com/query/latest>
- Tauri: <https://tauri.app/>
- FastAPI: <https://fastapi.tiangolo.com/>

### 3.2 后端服务层

当前 `main.py` 是 CLI 编排入口，客户端需要一个服务层承接浏览器请求。推荐新增一个薄 API 层：

- 框架：FastAPI
- 运行：uvicorn
- 长任务：后台任务队列，v1 可先用进程内任务管理器，后续再切 Celery / Dramatiq / RQ
- 实时输出：SSE 优先，WebSocket 作为交互式控制通道
- 数据校验：Pydantic
- 本地存储：SQLite 保存 session、配置快照、分析结果、报告索引
- 大文件策略：v1 不强制上传大体积 vmcore，优先由服务端读取本机路径

后端 API 层职责：

- 读取和校验分析配置。
- 创建分析 session。
- 调用现有 `init_analysis()` 和 `run_full_analysis()`。
- 捕获结构化结果、阶段事件、日志和错误。
- 将 CLI 输出转为客户端可消费的 JSON / event stream。
- 管理任务取消、重试和历史记录。

后端 API 层不负责：

- 重新实现 Search Agent。
- 重新实现 Analyze Agent。
- 重新实现 RAG。
- 直接把 LLM 密钥下发给浏览器。

### 3.3 桌面壳

推荐桌面壳采用 Tauri：

- 前端仍由 Vite 构建。
- Tauri 只负责加载前端资源和调用平台能力。
- 本地分析仍建议通过 Python API 服务完成，Tauri 不直接嵌入复杂 Python 分析进程。

桌面壳 v1 能力：

- 选择 `config.yaml`。
- 选择 `linux_path`、`vmcore`、`kdump_server`。
- 启动或连接本地 FastAPI 服务。
- 打开本地报告目录。
- 保存最近项目列表。

## 4. 推荐目录结构

建议在仓库内新增前端工作区：

```text
.
├── main.py
├── src/
│   └── agents/
├── server/
│   ├── app.py
│   ├── api/
│   ├── services/
│   └── schemas/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── app/
│   │   ├── pages/
│   │   ├── features/
│   │   ├── components/
│   │   ├── api/
│   │   ├── platform/
│   │   ├── stores/
│   │   └── styles/
│   └── tests/
├── desktop/
│   └── tauri/
└── docs/
```

说明：

- `server/` 是面向客户端的 HTTP 服务层，复用现有 Python 分析模块。
- `frontend/src/api/` 放置 TypeScript API SDK 和类型。
- `frontend/src/platform/` 放置浏览器与桌面差异适配。
- `desktop/tauri/` 只保留桌面壳配置和少量平台命令。

如果项目暂时不想引入 monorepo，可以先只新增 `frontend/` 和 `server/`，桌面壳留到第二阶段。

## 5. 前端架构

### 5.1 分层

前端分为五层：

1. App Shell
   - 全局布局、导航、主题、错误边界、全局 toast。

2. Pages
   - 页面级路由，例如 Dashboard、New Session、Session Detail、Reports、Settings。

3. Features
   - 面向业务域的模块，例如 session、analysis、taint-tree、rag、report、config。

4. Shared Components
   - Button、Dialog、Tabs、TreeView、CodeViewer、StatusBadge、LogPanel。

5. API / Platform
   - HTTP client、事件流 client、桌面/浏览器 adapter。

组件依赖方向：

```text
pages -> features -> components -> api/platform
```

业务组件不应直接依赖具体平台能力。涉及本地文件选择、打开目录、启动服务等能力时，必须通过 `platform` 层。

### 5.2 状态划分

服务端状态：

- session 列表
- session 详情
- 分析任务状态
- 阶段结果
- 日志事件
- 报告内容

使用 TanStack Query 管理。

本地状态：

- 当前选中的 session
- UI 面板展开状态
- taint tree 选中节点
- 日志过滤条件
- 主题和密度设置

使用 Zustand 管理。

表单状态：

- 新建分析配置
- 设置页
- API 地址配置

使用 React Hook Form 管理，并用 Zod 与后端 Pydantic schema 对齐。

## 6. 页面设计

### 6.1 Dashboard

用途：展示最近分析任务和系统状态。

内容：

- 最近 session 列表
- 每个 session 的状态：`created`、`validating`、`running`、`completed`、`failed`、`cancelled`
- 关键输入摘要：`linux_path`、`vmcore`、`enable_rag`、`build_codequery`
- 最近错误
- 后端服务状态
- 新建分析入口

交互：

- 点击 session 进入详情。
- 支持按状态和时间过滤。
- 支持重新运行上一次配置。

### 6.2 New Session

用途：创建一次 kdump 分析任务。

表单字段：

- `config_path`
- `linux_path`
- `gdb_path`
- `vmcore`
- `kdump_server`
- `kdump_host`
- `kdump_port`
- `kdump_args`
- `enable_rag`
- `build_codequery`
- `rag_cache_dir`
- `dry_run`

浏览器 Web 版处理方式：

- 用户输入服务端可访问的路径。
- 不假定浏览器本机路径等于分析服务路径。
- vmcore 大文件暂不走浏览器上传，除非后续明确需要远程上传能力。

桌面版处理方式：

- 通过 Tauri 文件选择器填充路径。
- 路径仍传给本地 API 服务校验。

校验：

- 前端做基础格式校验。
- 后端调用 `AppConfig.validate()` 做真实环境校验。
- dry run 成功后才允许正式运行。

### 6.3 Session Detail

用途：展示单次分析全过程。

推荐布局：

- 顶部：session 标题、状态、开始时间、耗时、操作按钮。
- 左侧：阶段导航。
- 中间：当前阶段主视图。
- 右侧：证据、日志、RAG、配置快照。

阶段：

1. 配置校验
2. 调试器启动
3. CodeQuery 初始化
4. Known Bug Search
5. RAG Context
6. Root Cause Analysis
7. Report

操作：

- 开始
- 取消
- 重试失败阶段
- 导出报告
- 复制关键结论

### 6.4 Known Bug Search View

展示 `KnownBugAnalysisResult`。

内容：

- `is_known_bug`
- `crash_fingerprint`
- `queries_tried`
- `evidence`
- `matched_url`
- `verification_details`
- `extra_info`

UI 重点：

- 查询记录用表格展示。
- matched URL 可点击打开。
- fingerprint 用紧凑信息块展示。
- 已知漏洞判定必须突出验证证据，而不是只展示 True / False。

### 6.5 Root Cause View

展示 `RootCauseAnalysisResult`。

内容：

- `root_cause`
- `trigger_path`
- `evidence`
- `fix_suggestion`
- `crash_site`
- `key_locations`
- `patch_sketch`
- `verification_todo`
- `uncertainty`

UI 重点：

- 根因结论置顶。
- 证据和不确定性分开显示。
- patch sketch 用代码块展示。
- source location 可跳转到源码查看面板。

### 6.6 Taint Tree View

展示 taint tree 分析过程。

数据来源：

- 当前 `AnalysisProcess` 已经有 `taint_tree_summary`。
- v1 可以先解析 summary 做只读展示。
- 后续建议后端输出结构化 tree JSON。

推荐结构化字段：

```json
{
  "root_id": "taint_xxx",
  "nodes": [
    {
      "id": "taint_xxx",
      "parent_id": null,
      "status": "done",
      "file_name": "fs/xxx.c",
      "line": 123,
      "variable_name": "obj",
      "current_function": "foo",
      "explain": "...",
      "end": false,
      "branch": null,
      "error": null
    }
  ]
}
```

UI 重点：

- React Flow 展示树结构。
- 节点颜色区分 `pending`、`running`、`done`、`failed`、`pruned`。
- 点击节点展示对象详情、分支原因、证据和错误。
- 支持定位到源码行。

### 6.7 RAG View

展示 RAG 和 PageIndex 状态。

内容：

- `pageindex_status`
- similar cases
- linux background
- retrieval warnings
- case persistence result

UI 重点：

- similar cases 和 linux background 必须分栏展示。
- 明确标注“辅助上下文，不是当前 crash 的直接证据”。
- 显示 source ref，便于人工复核。

### 6.8 Logs View

用途：实时展示分析日志和事件流。

能力：

- 自动滚动
- 暂停滚动
- 按级别过滤
- 按阶段过滤
- 搜索
- 下载日志

事件类型：

- `session.created`
- `config.validated`
- `debugger.started`
- `search.started`
- `search.completed`
- `analysis.started`
- `analysis.completed`
- `rag.status`
- `log.line`
- `error`

### 6.9 Reports

用途：查看和导出历史报告。

导出格式：

- Markdown
- JSON
- HTML

报告内容：

- 配置摘要
- known bug 结论
- root cause 结论
- taint tree 摘要
- RAG 使用记录
- 证据列表
- 修复建议
- 不确定性与验证 TODO

## 7. API 设计草案

### 7.1 Session API

```http
GET /api/health
GET /api/sessions
POST /api/sessions
GET /api/sessions/{session_id}
POST /api/sessions/{session_id}/validate
POST /api/sessions/{session_id}/run
POST /api/sessions/{session_id}/cancel
POST /api/sessions/{session_id}/rerun
GET /api/sessions/{session_id}/events
GET /api/sessions/{session_id}/report
```

### 7.2 Source API

```http
GET /api/sessions/{session_id}/source
GET /api/sessions/{session_id}/source/line
GET /api/sessions/{session_id}/source/search
```

用途：

- 读取源码文件。
- 跳转到 crash site。
- 跳转到 key locations。
- 在前端展示代码片段。

### 7.3 Config API

```http
POST /api/config/preview
POST /api/config/validate
GET /api/config/recent
```

说明：

- `preview` 返回解析后的配置，不启动 gdb。
- `validate` 对齐 `AppConfig.validate()`。
- `recent` 为桌面和 Web 管理最近配置提供数据。

### 7.4 Event Stream

推荐 v1 用 SSE：

```http
GET /api/sessions/{session_id}/events
```

事件示例：

```json
{
  "id": "evt_001",
  "session_id": "sess_001",
  "type": "search.completed",
  "stage": "known_bug_search",
  "timestamp": "2026-05-25T12:00:00Z",
  "payload": {
    "is_known_bug": false
  }
}
```

WebSocket 可以留给后续交互式能力，例如暂停、恢复、向运行中的 agent 追加人工备注。

## 8. 类型复用策略

Python 后端使用 Pydantic，前端使用 TypeScript。需要避免两端类型长期手写漂移。

推荐做法：

1. FastAPI 输出 OpenAPI schema。
2. 使用 `openapi-typescript` 生成 `frontend/src/api/schema.ts`。
3. 前端表单 schema 使用 Zod，但字段命名必须对齐 OpenAPI。
4. 业务组件只依赖生成类型和 API SDK，不手写重复接口。

关键前端类型：

- `AppConfigPreview`
- `AnalysisSession`
- `SessionStatus`
- `KnownBugAnalysisResult`
- `RootCauseAnalysisResult`
- `CrashFingerprint`
- `SearchQueryRecord`
- `TaintTreePayload`
- `PageIndexStatus`
- `AnalysisEvent`

## 9. Web 复用方案

为了保证客户端能在网页上复用，必须遵守以下设计：

### 9.1 Web-first 构建

- `frontend` 默认构建目标是浏览器静态资源。
- 所有业务 UI 都在浏览器环境可运行。
- 不把桌面专属能力写进 React 组件。
- 静态构建产物可以被 Nginx、FastAPI static mount、Tauri WebView 同时加载。

### 9.2 平台适配层

定义统一接口：

```ts
export interface PlatformAdapter {
  kind: "browser" | "desktop";
  pickFile?: (options: PickFileOptions) => Promise<string | null>;
  pickDirectory?: (options: PickDirectoryOptions) => Promise<string | null>;
  openExternal: (url: string) => Promise<void>;
  getApiBaseUrl: () => string;
}
```

浏览器实现：

- 不提供真实本地路径选择。
- 可以提供普通文本输入或上传入口。
- `openExternal` 使用 `window.open()`。

桌面实现：

- 通过 Tauri dialog 获取本地路径。
- 可以读取本地配置偏好。
- 可以启动或连接本地 API 服务。

业务组件只调用 `usePlatform()`，不关心运行环境。

### 9.3 可嵌入组件

建议把核心分析视图做成可嵌入组件：

```tsx
<Agent4KdumpClient apiBaseUrl="https://example.com/api" />
<SessionDetail sessionId="sess_001" />
<TaintTreeViewer data={tree} />
<RootCauseReport result={result} />
```

这样后续可以在其他网页系统中复用：

- 内部运维平台
- 安全分析门户
- CI 报告页面
- 漏洞 triage 页面

### 9.4 样式隔离

为了支持嵌入网页：

- 全局 CSS 只放 reset、theme variables 和字体变量。
- 组件样式使用可控 class 前缀，例如 `a4k-`。
- 暴露 `ThemeProvider`，允许宿主页面设置浅色、深色和紧凑密度。
- 不在组件中硬编码整页布局，嵌入组件必须能在任意容器宽度下工作。

## 10. 后端适配计划

### 10.1 拆分 CLI 与服务能力

当前 `main.py` 已经有可复用函数：

- `AppConfig.load()`
- `AppConfig.validate()`
- `init_analysis()`
- `run_full_analysis()`
- `render_*()`

服务层应优先调用这些函数，避免复制逻辑。

建议新增：

```text
server/
├── app.py
├── api/
│   ├── sessions.py
│   ├── config.py
│   └── source.py
├── services/
│   ├── session_store.py
│   ├── analysis_runner.py
│   └── event_bus.py
└── schemas/
    ├── config.py
    ├── session.py
    └── events.py
```

### 10.2 分析任务模型

每次运行创建一个 session：

```json
{
  "id": "sess_001",
  "status": "running",
  "config": {},
  "created_at": "...",
  "started_at": "...",
  "finished_at": null,
  "error": null,
  "results": {
    "parsed_search": null,
    "parsed_analyze": null
  }
}
```

状态机：

```text
created -> validating -> ready -> running -> completed
                                      ├── failed
                                      └── cancelled
```

### 10.3 长任务处理

v1 可以使用进程内任务管理：

- `AnalysisRunner` 用后台线程或 asyncio task 包装同步分析。
- 每个 session 有一个 event queue。
- SSE 从 event queue 读取事件。
- 取消任务时调用 session cancellation flag，并尽量触发 `kdump_analysis.stop()`。

后续如果需要多人或多机运行，再切换到外部队列。

## 11. 安全与权限

Web 版必须默认假定浏览器不可信：

- 浏览器不保存 LLM API Key。
- 浏览器不能任意读取服务端文件。
- 所有路径必须由后端校验和白名单控制。
- source API 只能读取当前 session 的 `linux_path` 下文件。
- 报告导出不能包含 `.env`、密钥或完整敏感路径，除非用户显式开启。
- matched URL 打开时使用新窗口并加安全属性。

桌面版也应遵守同样边界：

- Tauri 命令只暴露必要能力。
- 文件选择结果只用于填表，不直接绕过后端校验。
- 启动本地服务时明确端口和工作目录。

## 12. UI 设计原则

该客户端是工程分析工作台，不是营销页面。视觉应偏工具型：

- 信息密度适中，优先支持扫描、对比和复核。
- 主要界面采用左右分栏和可折叠面板。
- 结论、证据、日志、源码位置分区明确。
- 避免大面积装饰图、营销式 hero 和无关插画。
- 所有长文本区域支持复制。
- 所有关键判断都能追溯到证据、查询记录或源码位置。
- 错误信息给出可执行的下一步，例如缺少 `vmlinux`、`vmcore` 不存在、`gdb` 不可执行。

## 13. 开发阶段

### Phase 0：API 可行性整理

产出：

- 明确 `server/` 最小 API。
- 把 `AppConfig`、session、event、result schema 固化。
- 完成 dry-run API。

验收：

- 浏览器可提交配置并获得校验结果。
- 不启动实际分析也能显示配置摘要和错误。

### Phase 1：Web 前端骨架

产出：

- `frontend/` 初始化。
- App Shell、路由、主题、基础组件。
- Dashboard、New Session、Session Detail 空状态。
- API SDK 和 mock 数据。

验收：

- 前端可独立运行。
- mock session 能展示完整页面结构。
- 构建产物可以作为静态站点访问。

### Phase 2：真实 session 与事件流

产出：

- `POST /api/sessions`
- `POST /api/sessions/{id}/run`
- `GET /api/sessions/{id}/events`
- 前端实时日志面板和任务状态更新。

验收：

- 一次真实分析可以从前端启动。
- 日志和阶段状态实时刷新。
- 分析失败时前端展示后端错误。

### Phase 3：结果视图

产出：

- Known Bug Search View
- Root Cause View
- RAG View
- Report View

验收：

- `parsed_search` 和 `parsed_analyze` 能结构化展示。
- 报告可导出 Markdown 和 JSON。
- matched URL、证据、patch sketch、uncertainty 都能被复核。

### Phase 4：Taint Tree 与源码查看

产出：

- Taint Tree View
- Source Viewer
- key location 跳转
- crash site 跳转

验收：

- taint tree 可视化展示。
- 点击节点能查看对象详情。
- 点击源码位置能加载对应文件片段。

### Phase 5：桌面壳

产出：

- Tauri 配置。
- 桌面 platform adapter。
- 本地文件 / 目录选择。
- 本地 API 服务连接配置。

验收：

- 同一套前端在浏览器和桌面壳中运行。
- 桌面版可以选择本机路径并启动分析。
- Web 版仍可以通过输入服务端路径运行。

## 14. 测试计划

前端单元测试：

- API SDK 请求构造。
- session 状态 reducer。
- config 表单校验。
- result 展示组件。

前端集成测试：

- 新建 session。
- dry run 失败展示。
- 事件流驱动状态变化。
- 分析完成后展示报告。

端到端测试：

- 使用 mock API 跑 Playwright。
- 使用最小后端 fixture 跑一条 completed session。
- 验证浏览器静态部署可访问。

后端测试：

- config validate。
- session 状态流转。
- event stream。
- source path 沙箱限制。
- analysis runner 成功、失败、取消。

## 15. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| 当前分析流程是同步长任务 | 前端请求容易超时 | 使用 session + event stream，不把分析放在单个 HTTP 请求里 |
| vmcore 文件很大 | 浏览器上传成本高 | v1 使用服务端路径，后续再设计上传 |
| gdb / kdump 依赖本机环境 | Web 版无法直接访问用户机器 | Web 版连接远程分析服务，桌面版连接本地服务 |
| CLI 输出多为终端文本 | 前端难以结构化展示 | 服务层优先返回 `model_dump()` 结果，日志只作为辅助 |
| taint tree 当前主要是 summary | 图展示能力受限 | v1 只读展示 summary，后续增加结构化 tree payload |
| 前后端类型漂移 | 维护成本上升 | OpenAPI 生成 TypeScript 类型 |
| 桌面与 Web 分叉 | 复用失败 | 强制 platform adapter，业务组件禁止直接调用桌面 API |

## 16. v1 最小可交付范围

第一版应收敛到下面这些能力：

- Web 前端可以创建 session。
- Web 前端可以执行 dry run。
- Web 前端可以启动一次分析。
- 前端可以实时看到日志和阶段状态。
- 前端可以展示 known bug 搜索结果。
- 前端可以展示 root cause 结果。
- 前端可以导出 Markdown 报告。
- 同一套前端构建产物可以被浏览器部署，也可以被 Tauri 桌面壳加载。

只要完成这组能力，客户端就已经具备实际使用价值，并且不会破坏后续网页复用和桌面复用路径。
