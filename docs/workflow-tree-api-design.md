# 工作流修改 API 设计

本文档描述如何在当前 analysis workflow 上接入“污点分析树”，并保持接口尽量原语化。

目标不是重写整套流程，而是在现有四个节点基础上，把线性 `taint_object history` 替换成最小树结构。

相关现状：

- [analysis_process.py](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/src/agents/analysis_process.py)
- [analyze_agent.py](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/src/agents/analyze_agent.py)
- [taint-analysis-tree-design.md](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/docs/taint-analysis-tree-design.md)

---

## 1. 修改原则

工作流 API 的修改只遵守 4 条原则：

- 不改四个主节点名字
- 不引入新的复杂 manager / service 层
- 不把树搜索策略塞进 public API
- 只增加工作流真正需要的最小字段和最小方法

四个节点仍然是：

1. `start_debug`
2. `object_analysis`
3. `taint_analysis`
4. `root_cause_analysis`

---

## 2. 当前 API

当前 `AnalysisProcess` 的核心状态是：

```python
class State(TypedDict):
    messages: Annotated[AnyMessage, add_messages]
    taint_object: Annotated[list[TaintAnalysisObj], add_taint_obj]
    last_node: str
```

当前入口是：

```python
class AnalysisProcess:
    def __init__(self, max_retries: int = 2, max_taint_steps: int = 6) -> None:
        ...


def runAnalyzeAgent(max_retries: int = 2, max_taint_steps: int = 6):
    ...
```

这个 API 的问题不是不能跑，而是只能表示单路径。

---

## 3. 修改后的最小 Public API

## 3.1 `AnalysisProcess.__init__`

建议改成：

```python
class AnalysisProcess:
    def __init__(
        self,
        max_retries: int = 2,
        max_taint_steps: int = 6,
        max_branch_per_step: int = 2,
    ) -> None:
        ...
```

只新增一个参数：

- `max_branch_per_step`

用途：

- 控制每轮 `taint_analysis` 最多保留几个子分支

不建议现在就加：

- `search_strategy`
- `tree_config`
- `branch_score_fn`
- `memory_backend`

这些都太重。

## 3.2 `runAnalyzeAgent`

建议改成：

```python
def runAnalyzeAgent(
    max_retries: int = 2,
    max_taint_steps: int = 6,
    max_branch_per_step: int = 2,
):
    ...
```

保持入口风格和 `AnalysisProcess` 一致即可。

---

## 4. State API

线性 `taint_object` 应替换为树状态。

最小 state 建议如下：

```python
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    taint_tree: TaintTree
    active_node_id: str | None
    last_node: str
```

字段说明：

- `messages`：全局消息历史
- `taint_tree`：完整污点树
- `active_node_id`：当前正在展开的节点
- `last_node`：langgraph 当前节点记录

这里故意不单独暴露 `frontier`，因为它已经可以放在 `TaintTree` 内部。

---

## 5. TaintTree API

工作流不需要知道树的内部实现细节，只需要几个原语方法。

建议 `TaintTree` 提供下面这些方法：

```python
class TaintTree:
    def add_root(self, obj: TaintAnalysisObj, checkpoint: str) -> str:
        ...

    def add_child(
        self,
        parent_id: str,
        obj: TaintAnalysisObj,
        checkpoint: str,
        reason: str,
        evidence: list[str],
    ) -> str:
        ...

    def get_node(self, node_id: str) -> TaintNode | None:
        ...

    def get_active_path(self, node_id: str) -> list[TaintNode]:
        ...

    def pick_next(self) -> str | None:
        ...

    def mark_done(self, node_id: str, stop_reason: str) -> None:
        ...

    def terminal_paths(self) -> list[list[TaintNode]]:
        ...
```

这组 API 已经足够支撑 workflow。

说明：

- `add_root(...)`：写入第一层直接崩溃对象
- `add_child(...)`：给某个节点扩展一个上游候选
- `get_node(...)`：取节点
- `get_active_path(...)`：拿到当前分支路径，用于 prompt
- `pick_next(...)`：从树里选择下一个要展开的叶子
- `mark_done(...)`：标记某条分支停止
- `terminal_paths(...)`：为根因分析提供候选路径

不建议现在暴露：

- `merge_nodes(...)`
- `score_branch(...)`
- `rebalance_frontier(...)`

这些都不是 v1 必需。

---

## 6. Agent 输出 API

为了保持简单，`object_analysis` 和 `taint_analysis` 的输出不要同时大改。

## 6.1 `object_analysis`

保持不变，仍然返回一个 `TaintAnalysisObj`：

```python
TaintAnalysisObj
```

原因：

- 直接崩溃对象通常只有一个主候选
- 先保持第一层简单

## 6.2 `taint_analysis`

这里建议从“单对象输出”改成“候选分支列表输出”。

最小定义：

```python
from pydantic import BaseModel, Field


class TaintBranchProposal(BaseModel):
    obj: TaintAnalysisObj
    reason: str = Field(description="Why this upstream object is a valid branch")
    evidence: list[str] = Field(description="Concrete evidence for this branch")


class TaintBranchResult(BaseModel):
    branches: list[TaintBranchProposal]
```

约束：

- `branches` 至少 1 个
- 最多保留 `max_branch_per_step` 个
- 每个 branch 都必须有 `reason`
- 每个 branch 都必须至少有一条 `evidence`

这样已经够了。

不建议一开始就加：

- branch score
- branch label
- branch type

这些都不是原语。

---

## 7. 每个工作流节点怎么改

## 7.1 `start_debug`

最小变化：

- 初始化空 `taint_tree`
- `active_node_id=None`

建议新增一个内部方法：

```python
def _init_taint_tree(self) -> TaintTree:
    ...
```

## 7.2 `object_analysis`

当前做法是：

- 得到一个 `TaintAnalysisObj`
- 放进 `taint_object`

改成：

- 得到一个 `TaintAnalysisObj`
- `node_id = taint_tree.add_root(...)`
- `active_node_id = node_id`

内部不需要复杂 helper。

## 7.3 `taint_analysis`

当前做法是：

- 读 `history[-1]`
- 生成下一个对象

改成：

1. `node_id = taint_tree.pick_next()`
2. `path = taint_tree.get_active_path(node_id)`
3. 调 taint agent，返回 `TaintBranchResult`
4. 对每个 branch 调 `add_child(...)`
5. 如果当前节点应终止，调用 `mark_done(...)`
6. 再次 `pick_next()`，决定是继续 `taint_analysis` 还是进入 `root_cause_analysis`

最小内部 helper 建议：

```python
def _format_taint_path(self, path: list[TaintNode]) -> str:
    ...
```

这个 helper 只是为了拼 prompt，不要再拆更多层。

## 7.4 `root_cause_analysis`

当前做法是：

- 直接把线性 `history` 传给 root cause agent

改成：

1. `paths = taint_tree.terminal_paths()`
2. 选出 1~2 条最完整路径
3. 格式化成 prompt
4. 让 root cause agent 输出最终结论

最小内部 helper 建议：

```python
def _format_terminal_paths(self, paths: list[list[TaintNode]]) -> str:
    ...
```

---

## 8. 最小内部 API

为了让 `AnalysisProcess` 改动可控，内部最多新增下面几个 helper：

```python
def _init_taint_tree(self) -> TaintTree:
    ...

def _new_checkpoint(self, messages: list[AnyMessage]) -> str:
    ...

def _format_taint_path(self, path: list[TaintNode]) -> str:
    ...

def _format_terminal_paths(self, paths: list[list[TaintNode]]) -> str:
    ...
```

说明：

- `_init_taint_tree(...)`：创建空树
- `_new_checkpoint(...)`：给新节点记一个消息快照引用
- `_format_taint_path(...)`：把当前分支路径转成 prompt
- `_format_terminal_paths(...)`：把最终候选路径转成 root cause 输入

不建议现在加更多 helper。

---

## 9. v1 的最小行为规则

工作流改完后，v1 只要求以下行为：

- `object_analysis` 只产出 1 个根节点
- `taint_analysis` 每次最多扩展 2 个子节点
- 一个节点被展开后，不重复展开
- 节点终止后不再进入 `frontier`
- 当没有可展开节点时，进入 `root_cause_analysis`

这套规则足够把工作流从“单链”推进到“受限树”。

---

## 10. 一句话版本

工作流 API 的最小修改就是：

- 把 state 中的 `taint_object` 换成 `taint_tree + active_node_id`
- 把 `taint_analysis` 的输出从单个 `TaintAnalysisObj` 换成 `TaintBranchResult`
- 给 `TaintTree` 暴露 `add_root / add_child / pick_next / mark_done / terminal_paths` 这几个最小方法

做到这一步，工作流就已经具备树式污点分析能力了。
