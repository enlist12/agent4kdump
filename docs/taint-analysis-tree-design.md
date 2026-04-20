# 污点分析树设计

本文档把 [design.md](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/module_design/design.md#L135) 中“为污点分析建立 tree”的想法收敛成一个更简洁、更原语化的设计。

目标不是先做复杂搜索系统，而是先把“线性 taint history”升级成“可分叉、可回溯、可终止”的最小树结构。

---

## 1. 核心判断

当前实现里，污点分析本质上是单链路：

- state 里保存 `taint_object: list[TaintAnalysisObj]`
- 每轮 `taint_analysis` 只产生下一个对象

见 [analysis_process.py](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/src/agents/analysis_process.py#L40) 和 [analysis_process.py](/C:/Users/80163/Desktop/mdlBlackTool/agent4kdump/src/agents/analysis_process.py#L140)。

这个模型的问题是：

- 不能表达“一个对象有多个合理上游来源”
- 不能保留被放弃的候选路径
- 不能明确回溯模型在哪个条件点分叉

所以需要把“history list”改成“taint tree”。

---

## 2. 最小原语

污点分析树只保留 5 个原语：

- `node`
- `edge`
- `frontier`
- `checkpoint`
- `terminal`

### 2.1 `node`

一个 node 表示“当前正在追踪的一个污点对象”。

这个对象继续复用现有的 `TaintAnalysisObj`：

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

### 2.2 `edge`

一条 edge 表示：

“子节点是父节点的一个候选上游来源”。

edge 不需要复杂化，只要能说明：

- 为什么分叉
- 分叉依据是什么

### 2.3 `frontier`

`frontier` 是当前所有“还没展开”的叶子节点集合。

每次 `taint_analysis` 只从 `frontier` 里选一个节点继续扩展。

### 2.4 `checkpoint`

`checkpoint` 是这条分支对应的消息快照标识。

它不是完整消息本身，只是一个引用。

### 2.5 `terminal`

`terminal` 表示这条分支已经不该继续追踪。

例如：

- 到达外部输入
- 到达全局状态边界
- 到达配置边界
- 再往上已经没有新证据

---

## 3. 最小数据结构

## 3.1 节点

```python
from dataclasses import dataclass


@dataclass(slots=True)
class TaintNode:
    id: str
    parent_id: str | None
    obj: TaintAnalysisObj
    checkpoint: str
    done: bool = False
    stop_reason: str = ""
```

这个定义只保留最小信息：

- `id`：节点 id
- `parent_id`：父节点 id
- `obj`：当前污点对象
- `checkpoint`：消息快照引用
- `done`：是否终止
- `stop_reason`：为什么终止

## 3.2 边

```python
@dataclass(slots=True)
class TaintEdge:
    parent_id: str
    child_id: str
    reason: str
    evidence: list[str]
```

这里不放 score，不放 hypothesis id，不放太多状态。
v1 只要求“能解释为什么有这个子节点”。

## 3.3 树

```python
@dataclass(slots=True)
class TaintTree:
    root_id: str | None
    nodes: dict[str, TaintNode]
    edges: list[TaintEdge]
    frontier: list[str]
```

含义：

- `root_id`：根节点
- `nodes`：所有节点
- `edges`：所有边
- `frontier`：待扩展节点

这就够了。

---

## 4. 树如何生长

## 4.1 `start_debug`

不急着建复杂根节点。

可以只做一件事：

- 初始化空树

```python
tree = TaintTree(
    root_id=None,
    nodes={},
    edges=[],
    frontier=[],
)
```

## 4.2 `object_analysis`

找到直接崩溃对象后：

1. 建一个节点
2. 设为 `root_id`
3. 放进 `frontier`

```python
root = TaintNode(
    id="n1",
    parent_id=None,
    obj=taint_obj,
    checkpoint="cp1",
)
```

## 4.3 `taint_analysis`

每次只做下面几步：

1. 从 `frontier` 取一个节点
2. 让 agent 找它的上游候选
3. 为每个候选创建一个子节点
4. 建立边
5. 更新 `frontier`

如果当前节点已经到达边界，就：

- `done=True`
- 写 `stop_reason`
- 不再扩展它

## 4.4 `root_cause_analysis`

根因分析阶段不需要遍历整棵树做复杂搜索。

v1 只要做两件事：

- 找出所有 `done=True` 的路径
- 选一条证据最完整的路径生成结论

如果没有 terminal path，就选当前最深的一条路径，但必须在结果里说明“不完整”。

---

## 5. 分叉规则

不是每步都分叉。

只有满足下面条件才允许分叉：

- 存在两个以上合理上游来源
- 每个候选都能给出最少一条证据

典型分叉点：

- `if/else` 不同赋值路径
- 多个返回值来源
- 参数 / 结构体字段 / 全局状态都可能是源头

如果只是“模型觉得也许可能”，但没有源码依据，不应分叉。

---

## 6. 回溯规则

tree 不直接存整个消息历史。

只做：

- 全局保存 `messages`
- 节点里保存 `checkpoint`

这样回溯一个分支时，只需要：

1. 找到该节点
2. 沿父链回到根
3. 恢复这一条路径对应的 checkpoint

所以：

- tree 记录结构
- checkpoint 记录上下文位置

这比把完整对话复制到每个节点里更原语，也更稳。

---

## 7. 终止与剪枝

v1 不做复杂打分，只做最直接的终止和剪枝。

### 7.1 终止

遇到下面情况直接终止：

- `obj.end == True`
- 回溯到外部输入边界
- 回溯到配置或全局边界
- 新对象与父对象相同，说明收敛

### 7.2 剪枝

遇到下面情况直接丢弃候选子节点：

- 和 crash facts 冲突
- 和源码读取结果冲突
- 没有具体证据
- 与已有节点完全相同

---

## 8. 与当前实现的最小衔接

当前 state：

```python
class State(TypedDict):
    messages: Annotated[AnyMessage, add_messages]
    taint_object: Annotated[list[TaintAnalysisObj], add_taint_obj]
    last_node: str
```

建议改成：

```python
class State(TypedDict):
    messages: Annotated[AnyMessage, add_messages]
    taint_tree: TaintTree
    active_node_id: str | None
    last_node: str
```

这里故意不加太多字段。

说明：

- `taint_tree`：完整树
- `active_node_id`：当前展开的节点

如果后面确实需要，再补 `frontier` 到 state；否则也可以先把 `frontier` 放进 `TaintTree` 内部管理。

---

## 9. v1 推荐实现边界

为了保持原语化，v1 建议限制为：

- 每轮最多扩展 2 个子节点
- 不做复杂 branch score
- 不做 merge 机制
- 不做全局 best-first search
- 只支持单活跃分支 + 受限分叉

也就是：

- 先有树结构
- 再有简单分叉
- 最后再考虑搜索策略

这个顺序更稳。

---

## 10. 一句话总结

污点分析树的最小设计就是：

“把当前的线性 `taint_object history`，替换成一个由 `TaintNode + TaintEdge + frontier + checkpoint` 组成的树；每次只向上扩展一跳，只在有证据时分叉，在到达边界时终止。”
