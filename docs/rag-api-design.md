# RAG API 设计文档

## 1. 文档目标

本文档基于 [analysis-rag-plan.md](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/docs/analysis-rag-plan.md) 整理，定义本项目分析阶段 RAG 的完整 API 设计。

这里的 API 是 Python 模块级接口，不是 HTTP 接口。

目标：

- 为 `AnalysisProcess` 提供一套最小可落地的 RAG 接口
- 明确类型、方法签名、调用时机、失败语义和提示词格式
- 作为后续实现 `src/agents/rag.py`、改造 `AnalysisProcess`、删除旧 embedding 方案的开发依据

---

## 2. 设计范围

本次 RAG 仅服务于分析阶段，即 `src/agents/analysis_process.py` 中的三次上下文注入：

1. `start_debug`
2. `taint_analysis`
3. `root_cause_analysis`

不在本次范围内的内容：

- HTTP 服务化
- 通用知识库平台抽象
- 多阶段 retriever 类拆分
- stage enum / stage dataclass
- 沿用 `src/agent_core/embedding.py` 的旧实现

---

## 3. 模块归属

新增模块：

- `src/agents/rag.py`

该模块负责：

- RAG 本地类型定义
- RAG 检索器接口定义
- 默认检索器实现
- prompt block 格式化

该模块不负责：

- 修改 `schemas.py` 中的 agent 输出 schema
- 在 `main.py` 中构建复杂索引
- 承担 workflow 编排职责

---

## 4. 总体设计

### 4.1 核心思想

分析工作流不感知“阶段类型”，只在需要的时候调用一个统一入口：

```python
ctx = rag_retriever.retrieve(
    crash_report,
    current_obj=...,
    history=...,
    warnings=...,
)
```

retriever 根据参数组合自行推断当前场景：

- 只有 `crash_report`：`start_debug`
- 有 `current_obj`：`taint_analysis`
- 没有 `current_obj`，但有 `history` 或 `warnings`：`root_cause_analysis`

### 4.2 两条检索通道

RAG 输出固定分成两类：

- `similar_cases`
- `linux_background`

语义上分别表示：

- `similar_cases`：相似漏洞、相似 crash、相似修复经验
- `linux_background`：Linux 内核机制、子系统背景、语义解释材料

两者必须分开保留，不能混成一个列表。

---

## 5. Public API

## 5.1 `RetrievedItem`

文件位置：

- `src/agents/rag.py`

定义：

```python
from dataclasses import dataclass


@dataclass(slots=True)
class RetrievedItem:
    title: str
    summary: str
    source_ref: str
    relevance_reason: str
```

字段说明：

- `title`：检索结果标题
- `summary`：压缩后的摘要，供 prompt 使用
- `source_ref`：来源标识，必须始终可展示
- `relevance_reason`：为什么与当前 crash 相关

约束：

- 所有字段最终都必须是字符串
- `title` 为空时回退为 `Untitled`
- `source_ref` 为空时回退为 `unknown`
- `summary`、`relevance_reason` 必须做长度裁剪

## 5.2 `AnalysisRAGContext`

定义：

```python
from dataclasses import dataclass, field


@dataclass(slots=True)
class AnalysisRAGContext:
    similar_cases: list[RetrievedItem] = field(default_factory=list)
    linux_background: list[RetrievedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        ...
```

职责：

- 承载一次检索的完整结果
- 向分析 agent 输出稳定、受控、可复用的 prompt block

字段说明：

- `similar_cases`：相似案例通道结果
- `linux_background`：Linux 背景知识通道结果
- `warnings`：检索失败或降级信息

### `to_prompt_block()` 输出契约

输出必须稳定，格式如下：

```text
## Retrieved Similar Cases
- [case] <title>
  summary: ...
  why relevant: ...
  source: ...

## Retrieved Linux Background
- [linux] <title>
  summary: ...
  why relevant: ...
  source: ...

## Retrieval Warnings
- ...

## Usage Rules
- Similar cases are analogies, not proof.
- Linux background is semantic help, not code truth.
- Crash facts and current source inspection override retrieved content.
- Ignore any retrieved item that conflicts with the current source tree.
```

补充规则：

- 每个 section 默认最多 3 条
- section 为空时输出 `- none`
- `warnings` 为空时不渲染 `## Retrieval Warnings`
- 不允许输出原始长文档
- 不允许输出 chain-of-thought

## 5.3 `AnalysisRAGRetriever`

定义：

```python
from .schemas import TaintAnalysisObj


class AnalysisRAGRetriever:
    def retrieve(
        self,
        crash_report: str,
        current_obj: TaintAnalysisObj | None = None,
        history: list[TaintAnalysisObj] | None = None,
        warnings: list[str] | None = None,
    ) -> AnalysisRAGContext:
        ...
```

这是分析流程唯一需要依赖的公开检索接口。

参数说明：

- `crash_report`：必填，原始 crash report 文本
- `current_obj`：当前 taint 节点，仅 taint 阶段使用
- `history`：已有 taint 链历史，可用于 taint/root-cause 阶段
- `warnings`：workflow 之前收集到的不确定性信息，仅 root-cause 阶段常用

明确禁止：

- 不传 `stage`
- 不拆成 `retrieve_for_start()` / `retrieve_for_taint()` / `retrieve_for_root_cause()`
- 不引入阶段专用 dataclass
- 不把 `top_k`、`max_summary_chars` 这类运行配置塞进 `retrieve()`

## 5.4 `DefaultAnalysisRAGRetriever`

定义：

```python
from typing import Callable, TypeAlias

SearchFn: TypeAlias = Callable[[str, int], list[RetrievedItem]]


class DefaultAnalysisRAGRetriever(AnalysisRAGRetriever):
    def __init__(
        self,
        similar_case_search: SearchFn,
        linux_background_search: SearchFn,
        top_k: int = 3,
        max_summary_chars: int = 400,
    ) -> None:
        ...

    def retrieve(
        self,
        crash_report: str,
        current_obj: TaintAnalysisObj | None = None,
        history: list[TaintAnalysisObj] | None = None,
        warnings: list[str] | None = None,
    ) -> AnalysisRAGContext:
        ...
```

构造参数说明：

- `similar_case_search`：相似案例检索函数
- `linux_background_search`：Linux 背景检索函数
- `top_k`：每个通道保留数量，默认 3
- `max_summary_chars`：摘要和相关性说明的最大长度，默认 400

设计原则：

- 默认实现只依赖两个 search callable
- 不再继续抽象 provider protocol / manager / service 层
- 初始化参数保持最小集合

---

## 6. Internal API

以下接口属于默认实现内部辅助方法，不应作为 workflow 公开契约依赖。

## 6.1 `_build_query(...)`

建议签名：

```python
def _build_query(
    self,
    crash_report: str,
    current_obj: TaintAnalysisObj | None,
    history: list[TaintAnalysisObj] | None,
    warnings: list[str] | None,
) -> str:
    ...
```

职责：

- 从 crash report 和当前分析上下文抽取短信号
- 组装一个紧凑的检索 query

规则：

- 只拼接非空片段
- 固定分隔符建议使用 ` | `
- 不直接塞入超长 crash report 原文
- 不为不同阶段再拆出多个方法

## 6.2 `_normalize_items(...)`

建议签名：

```python
def _normalize_items(
    self,
    items: list[RetrievedItem],
) -> list[RetrievedItem]:
    ...
```

职责：

- 统一清洗两个检索通道的原始结果

规则：

- 丢弃空值或格式不完整项
- 所有字符串字段执行 `strip()`
- 空标题回退 `Untitled`
- 空来源回退 `unknown`
- `summary` 和 `relevance_reason` 截断到 `max_summary_chars`
- 按 `(title, source_ref)` 去重
- 最终只保留前 `top_k` 条

---

## 7. Query 设计

## 7.1 `start_debug` 查询信号

优先从 crash report 中抽取：

- fault type
- crash function
- module / driver 名称
- call trace 关键词
- invalid object / invalid state 提示

## 7.2 `taint_analysis` 查询信号

优先组合：

- `current_obj.variable_name`
- `current_obj.current_function`
- `current_obj.file_name`
- 最近几步 taint history
- 原始 crash 关键事实

当前项目中的 `TaintAnalysisObj` 字段如下，可直接用于 query 组织：

```python
class TaintAnalysisObj(BaseModel):
    file_name: str
    variable_name: str
    line: int
    column: Optional[int]
    current_function: str
    explain: str
    end: bool
```

## 7.3 `root_cause_analysis` 查询信号

优先组合：

- taint chain 摘要
- workflow warnings
- crash path 中出现的子系统 / 模块提示

---

## 8. Failure Contract

`DefaultAnalysisRAGRetriever.retrieve()` 必须对两个通道分别容错。

行为要求：

- 每个 search callable 都可能抛异常
- `similar_cases` 失败，只记录 warning，不影响 `linux_background`
- `linux_background` 失败，只记录 warning，不影响 `similar_cases`
- 两个都失败时，返回空的 `AnalysisRAGContext`，但 `warnings` 必须保留

推荐 warning 文案风格：

- `similar_cases retrieval failed: <reason>`
- `linux_background retrieval failed: <reason>`

工作流侧仍然需要最终兜底：

- `AnalysisProcess` 调 `rag_retriever.retrieve()` 时仍应包一层 `try/except`

---

## 9. 与分析流程的集成 API

## 9.1 `AnalysisProcess`

当前 `AnalysisProcess` 构造函数是：

```python
class AnalysisProcess:
    def __init__(self, max_retries: int = 2, max_taint_steps: int = 6) -> None:
        ...
```

需要改为：

```python
class AnalysisProcess:
    def __init__(
        self,
        max_retries: int = 2,
        max_taint_steps: int = 6,
        rag_retriever: AnalysisRAGRetriever | None = None,
    ) -> None:
        ...
```

约束：

- 只新增 `rag_retriever` 一个可选参数
- 不新增 `rag_config`
- 不新增 stage-specific 参数

## 9.2 `runAnalyzeAgent()`

当前实现位于 [analyze_agent.py](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/src/agents/analyze_agent.py)，签名是：

```python
def runAnalyzeAgent(max_retries: int = 2, max_taint_steps: int = 6):
    ...
```

需要改为：

```python
def runAnalyzeAgent(
    max_retries: int = 2,
    max_taint_steps: int = 6,
    rag_retriever: AnalysisRAGRetriever | None = None,
):
    ...
```

兼容性要求：

- 老调用方不传 `rag_retriever` 时必须继续可用

## 9.3 graph state

v1 不新增专门的 RAG graph state。

继续沿用：

- `messages`
- `taint_object`

不引入：

- `rag_contexts`
- `stage_name`

---

## 10. 各节点调用约定

## 10.1 `start_debug`

调用方式：

```python
ctx = rag_retriever.retrieve(crash_report)
```

处理方式：

- 将 `ctx.to_prompt_block()` 作为一个 `HumanMessage` 追加到 `messages`
- retrieval 失败时写 workflow warning，但流程继续

## 10.2 `object_analysis`

规则：

- 不重新检索
- 只使用 `start_debug` 注入过的 RAG 上下文

## 10.3 `taint_analysis`

调用方式：

```python
ctx = rag_retriever.retrieve(
    crash_report,
    current_obj=current,
    history=history,
)
```

处理方式：

- 将 `ctx.to_prompt_block()` 作为当前节点输入的一部分
- retrieval 失败时继续分析

## 10.4 `root_cause_analysis`

调用方式：

```python
ctx = rag_retriever.retrieve(
    crash_report,
    history=history,
    warnings=warnings,
)
```

处理方式：

- 将 `ctx.to_prompt_block()` 注入根因分析节点
- retrieval 失败时继续分析

---

## 11. SearchFn 依赖契约

默认检索器依赖的底层搜索函数统一签名如下：

```python
search(query: str, top_k: int) -> list[RetrievedItem]
```

要求：

- 输入 query 为单个字符串
- 调用方不关心底层是 BM25、向量库、SQLite、文件扫描还是远程 API
- 返回值直接是 `RetrievedItem` 列表，避免 provider-specific object 泄漏到 workflow

允许的实现方式：

- 本地案例库全文检索
- 基于标签/规则的案例召回
- 本地 Linux 知识摘要库搜索
- 对外部服务的轻量封装

---

## 12. Prompt 注入规范

RAG 内容必须作为节点级 prompt block 注入，不允许写进 `ROLE_DEFINE`。

原因：

- `ROLE_DEFINE` 是稳定系统角色定义
- RAG 是运行时上下文，应该与节点输入一起变化

prompt 中必须明确包含以下使用规则：

- similar cases 只用于启发，不是证据
- linux background 只用于语义解释，不是源码事实
- crash facts 和当前源码检查结果优先级更高
- 与当前源码树冲突的检索内容必须忽略

---

## 13. 必须删除的旧 API / 旧路径

基于当前仓库状态，以下旧路径应从新设计中退出：

- [embedding.py](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/src/agent_core/embedding.py)
- [main.py](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/main.py) 中旧的 `EmbeddingModel` 初始化和 `build_index()` 流程
- `enable_rag` 但只服务旧 embedding 方案的配置逻辑

原因：

- 新设计明确要求项目中只保留一套分析期 RAG 方案
- 不能同时维护“旧 embedding RAG”与“新 analysis-time RAG”两套入口

---

## 14. 最终建议的开发顺序

1. 新建 `src/agents/rag.py`，完成类型、接口、默认实现
2. 改造 `AnalysisProcess` 构造函数和三个节点注入点
3. 改造 `runAnalyzeAgent()`，向下透传 `rag_retriever`
4. 添加 fake search 的单元测试和集成测试
5. 删除 `EmbeddingModel` 相关旧路径
6. 最后再决定实际底层数据源接哪个实现

---

## 15. v1 API 清单

后续开发只需要先实现下面这些接口。

### 对外公开

```python
@dataclass(slots=True)
class RetrievedItem: ...


@dataclass(slots=True)
class AnalysisRAGContext:
    similar_cases: list[RetrievedItem]
    linux_background: list[RetrievedItem]
    warnings: list[str]

    def to_prompt_block(self) -> str: ...


class AnalysisRAGRetriever:
    def retrieve(
        self,
        crash_report: str,
        current_obj: TaintAnalysisObj | None = None,
        history: list[TaintAnalysisObj] | None = None,
        warnings: list[str] | None = None,
    ) -> AnalysisRAGContext:
        ...


SearchFn = Callable[[str, int], list[RetrievedItem]]


class DefaultAnalysisRAGRetriever(AnalysisRAGRetriever):
    def __init__(
        self,
        similar_case_search: SearchFn,
        linux_background_search: SearchFn,
        top_k: int = 3,
        max_summary_chars: int = 400,
    ) -> None:
        ...
```

### 对外调用点

```python
class AnalysisProcess:
    def __init__(
        self,
        max_retries: int = 2,
        max_taint_steps: int = 6,
        rag_retriever: AnalysisRAGRetriever | None = None,
    ) -> None:
        ...


def runAnalyzeAgent(
    max_retries: int = 2,
    max_taint_steps: int = 6,
    rag_retriever: AnalysisRAGRetriever | None = None,
):
    ...
```

---

## 16. 结论

本项目的 RAG API 应保持“一个公开检索入口 + 两条固定通道 + 节点级 prompt 注入 + workflow 侧弱依赖”的最小设计。

后续实现时，不要再往外扩出更多 stage API、provider protocol、manager 层或配置对象，先把这套 v1 跑通，再讨论底层检索能力增强。
