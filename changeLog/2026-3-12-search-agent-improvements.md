# Search Agent 改进 - 2026-03-12

## 版本历史
- **上午版本**：初始改进（函数梯度、四轮搜索、去除置信度）
- **下午版本**：增强搜索策略、移除工具示例、增加搜索日志要求
- **晚上版本 ⭐**：**重大重构 - 从"Root Cause 分析"转向"症状匹配"**

## 问题背景
1. **Syzbot 标题问题**：Syzbot 报告的标题经常使用 call trace 中间层的语义丰富的函数（如 `kobject_cleanup`），而不是 RIP 位置的底层函数（如 `list_del`）
2. **误报问题**：Agent 有时声称找到了匹配，但实际验证后发现不是同一个漏洞
3. **搜索策略问题**（2026-03-12 下午更新）：
   - GPT-4o 仍使用底层函数（`__list_del_entry_valid`）而非语义函数（`kobject_cleanup`）
   - `web_search` 参数中的示例可能误导 Agent 按固定格式搜索
   - 缺少"向上递归"策略：底层函数搜索失败时，应向上尝试更高层函数

4. **过度强调 Root Cause 问题**（2026-03-12 晚上发现）⭐ 最关键的问题：
   - **工作流错位**：当前阶段目标是"匹配已知漏洞"，不是"分析根本原因"。Root cause 分析应该在判定为未知漏洞后进行
   - **认知负荷过大**：同时要求深度 root cause 分析和 web search 匹配，导致 lost in middle 和注意力分散
   - **判断标准错误**：匹配已知漏洞≠完全理解根本原因。只需要：
     * Call trace 是否匹配
     * Patch 描述的症状是否与当前情况相符
     * 源码是否已包含 patch

## 改进方案

### 1. 提示词改进 (prompt.py)

#### 1.1 Phase 2 查询策略增强（下午进一步增强）
- **新增"函数梯度"（Function Ladder）**概念 ⭐：
  ```
  Bottom (RIP):     __list_del_entry_valid  ← 泛型辅助函数（搜索时跳过）
                    list_del                 ← 泛型辅助函数（搜索时跳过）
  Middle (Driver):  gpiodevice_release       ← 驱动特定函数（适合搜索）
                    device_release           ← 框架函数（适合搜索）
  Top (Subsystem):  kobject_cleanup          ← 语义函数（最佳搜索 ⭐）
  ```
- **四轮搜索策略（Upward Recursion）**：
  - **Round 1**: 从顶层语义函数开始（`kobject_cleanup`）
  - **Round 2**: 如果 Round 1 失败，向下一层（`device_release`）
  - **Round 3**: 如果 Round 2 失败，尝试驱动函数（`gpiodevice_release`）
  - **Round 4**: 扩大范围（CVE 数据库、补丁仓库等）
- **查询优先级调整**：
  - **Query 1（最高优先级）**：`"<panic_type> in <top_semantic_function>" site:syzkaller.appspot.com`
    - 例如：`"general protection fault in kobject_cleanup" site:syzkaller.appspot.com`
    - 直接匹配 Syzbot 标题格式
  - Query 2-6：渐进式降低特异性
- **从 5-8 个查询增加到 8-10 个查询**，覆盖所有 4 轮搜索策略
- **明确禁止**：不要用 `__list_del_entry_valid`、`list_del` 等泛型函数开始搜索

#### 1.2 Phase 3 验证强化

**上午版本**：
- **量化评分系统**：
  - Call Trace Match: 30% 权重
  - Root Cause Match: 40% 权重（最重要）
  - Patch Verification: 20% 权重
  - Falsification Test: 10% 权重

**晚上重构版本** ⭐：
- **Checkpoint 2 重大变更**：从"Root Cause Match"改为**"Symptom Match"**
  - **不再要求**：完全理解根本原因、深度分析 bug 机制
  - **只需要检查**：
    * 读取 patch 的描述/commit message
    * 对比表面症状是否相符（panic type、crash location、触发场景）
    * 不需要理解"为什么"，只需要确认"症状是否相似"
  - **示例**：
    ```
    Patch 说: "GPF in kobject_cleanup due to list corruption when device ref drops to 0"
    Your crash: GPF in kobject_cleanup, call trace 显示 device_release → kobject_cleanup
    → 症状匹配 ✓ (不需要分析为什么 list 被破坏)
    ```

- **Checkpoint 3 简化**：
  - 去掉过度的 GDB 分析要求
  - 主要任务：对比源码是否包含 patch
  - GDB 只是可选的快速确认（如检查 NULL），不是必需的深度分析

#### 1.3 新增 Phase 4：Self-Verification（自我验证）

**上午版本**：
强制要求在报告前回答 4 个检查问题：
1. 能否明确陈述两个 crash 的根本原因？
2. 是否对比了源码和补丁？
3. 是否考虑了其他可能的解释？
4. 各检查点的量化评分

**晚上重构版本** ⭐：
1. **"症状是否匹配?"** （不再是"根本原因"）
   - YOUR crash symptoms: [从表面观察]
   - CANDIDATE description: [patch 描述说什么]
   - 症状是否对齐？（不需要深入理解为什么）
2. **"是否验证了 patch?"** （保持不变）
3. **"可能是不同 bug 吗?"** （保持不变）
4. **评分调整**：
   - Call Trace Match: __/10
   - **Symptom Match** (改名): __/10 (最重要 - 症状与 patch 描述是否对齐?)
   - Patch Verification: __/10
   - Falsification Test: __/10

### 1.4 Phase 1 简化（2026-03-12 晚上重构）⭐ 重大变更

**之前的问题**：
- 要求深度 root cause 分析（GDB deep dive、源码分析、形成假设）
- 导致认知负荷过大、lost in middle

**现在的设计**：
- **Step 1.1**: 获取 crash 概览（panic type、RIP、call trace）
- **Step 1.2**: **快速观察，不做深度分析**
  - 只需要 `bt`、`list` 看一下代码位置
  - 如果有明显的 NULL/invalid 值，简单记录（`print ptr`）
  - **目标**：收集症状，**不分析根因**
- **Step 1.3**: 构建函数梯度（为搜索准备）

**关键原则**：这个阶段只收集数据，不做深度分析。Root cause 分析留给后续的专门 agent。

### 2. 代码改进 (search_agent.py)

#### 2.1 增强数据模型
```python
class KnownBugAnalysisResult(BaseModel):
    is_known_bug: bool  # 强制二元决策，不允许模糊地带
    evidence: str  # 必须包含 4-checkpoint 评分
    matched_url: Optional[List[str]]
    extra_info: Optional[str]
    verification_details: Optional[str]  # 新增：Phase 4 自检答案，必须包含源码对比结果
```

**关键改动**：
- **移除 `confidence_score`**：不提供置信度，强制 Agent 做出明确决策
- 如果不确定，必须报告 `is_known_bug=False`
- **所有 Optional 字段添加 `default=None`**：修复 Pydantic 验证错误

#### 2.2 结果质量验证函数（下午增强）
```python
def verify_result_quality(result) -> tuple[bool, str]:
```
如果声称找到匹配（`is_known_bug=True`），必须满足：
- 提供 `matched_url`
- 提供详细的 `verification_details`（至少 100 字符）
- `evidence` 中包含 "Call Trace" 和 "Root Cause" 关键词
- **必须包含源码对比结果**：证明当前源码**不包含补丁**（仍然是 vulnerable 状态）

**新增（下午）**：如果报告未找到（`is_known_bug=False`），必须：
- 在 `evidence` 中记录搜索尝试（哪些查询、多少结果）
- 至少 3 处提到 "query"/"search"/"tried" 等搜索相关词汇
- 如果搜索证据不足，质量检查会拒绝并要求重试

如果源码已经包含补丁，质量检查会直接拒绝该结果。

#### 2.3 重试机制
```python
def runSearchAgent(max_retries: int = 2):
```
- 默认最多重试 2 次（共 3 次尝试）
- 每次重试时向 agent 反馈上次失败的原因
- 如果 3 次尝试后仍然声称是已知漏洞但质量不达标，自动降级为 "unknown bug"

### 3. 工具改进 (WebSearch.py) - 2026-03-12 下午新增

#### 3.1 移除误导性示例
**修改前**：
```python
query: Annotated[str, "The search query (e.g., 'Linux kernel gpiodevice_release null-ptr-deref syzbot')"]
```

**修改后**：
```python
query: Annotated[str, "The search query. Construct freely based on your analysis - no fixed format required."]
```

**原因**：示例可能误导 Agent 按固定格式搜索，限制了查询的灵活性和创造性。

## 核心设计思想的转变（2026-03-12 晚上）⭐

### 之前的设计（有问题）
```
判断是否已知漏洞 = 深度理解 root cause + 完全匹配根本原因
    ↓
要求：GDB deep dive + 源码分析 + 形成假设 + 对比 root cause
    ↓
问题：
  1. 工作流错位（root cause 分析应该在后续阶段）
  2. 认知负荷过大（同时做分析和搜索）
  3. Lost in middle（上下文过长，注意力分散）
```

### 现在的设计（正确）
```
判断是否已知漏洞 = 表面症状匹配 + 源码对比
    ↓
要求：快速观察 + 构建函数梯度 + 搜索 + 对比症状 + 验证源码
    ↓
优势：
  1. 任务明确（只匹配，不分析根因）
  2. 认知负荷合理（专注于搜索和匹配）
  3. 更高的成功率（不需要完全理解 bug）
```

### 关键原则：症状匹配 vs 根因分析

| 维度 | 症状匹配（当前阶段） | 根因分析（后续阶段） |
|------|---------------------|---------------------|
| **目标** | 判断是否已知漏洞 | 理解 bug 如何发生 |
| **深度** | 表面观察 | 深度追踪 |
| **数据** | Call trace + patch 描述 | GDB + 源码 + 逻辑推理 |
| **判断依据** | 症状是否相似 | 机制是否相同 |
| **示例** | "都是 GPF in kobject_cleanup" ✓ | "为什么 list 被破坏？" |

### 具体差异示例

**场景**：GPF in kobject_cleanup

**之前的要求**（过度）：
1. 用 GDB 深度分析：list 为什么被破坏？谁修改了它？
2. 阅读源码：引用计数如何管理？cleanup 路径是什么？
3. 形成假设："因为 X 在 Y 时被 Z 修改导致..."
4. 对比 candidate 的 root cause 是否完全一致

**现在的要求**（合理）：
1. 快速观察：crash 在 kobject_cleanup，call trace 是什么
2. 搜索：找 "GPF in kobject_cleanup" 相关的 patch
3. 对比症状：
   - Patch 说："GPF in kobject_cleanup when device released"
   - Your crash：GPF in kobject_cleanup，call trace 有 device_release
   - → 症状匹配 ✓
4. 验证源码：patch 的改动在源码里吗？
   - 不在 → 可能是这个 bug ✓
   - 在 → 不是这个 bug ✗

## 使用效果

### 对 Syzbot 标题问题（增强版）
- **函数梯度策略**：
  ```
  优先级：kobject_cleanup (顶层) > device_release (中层) > gpiodevice_release (底层)
  禁止：__list_del_entry_valid, list_del (泛型辅助函数)
  ```
- **四轮递归搜索**：如果顶层函数搜索失败，自动向下尝试下一层
- **示例搜索路径**：
  ```
  Round 1: "general protection fault in kobject_cleanup" → 找到！
  （或）
  Round 1: "general protection fault in kobject_cleanup" → 0 results
  Round 2: "general protection fault in device_release" → 0 results  
  Round 3: "gpiodevice_release general protection fault" → 找到！
  ```
- 命中率应显著提升，且不再从底层泛型函数开始搜索

### 对误报问题（增强版）
- 4 层防护机制：
  1. **Prompt 中的 Phase 3 Checkpoint 3**：强制对比源码和补丁
     - 如果源码已包含补丁 → 自动判定为不匹配
  2. **Prompt 中的 Phase 4 强制自检**：二元决策逻辑
     - 移除置信度评分，强制回答 True/False
     - 不确定时默认为 False
  3. **代码层面的 `verify_result_quality`**：质量门槛检查
     - 检查是否包含源码对比证据
     - **新增**：检查是否记录了足够的搜索尝试（`is_known_bug=False` 时）
  4. **不达标时的自动重试**：最多 3 次尝试
- 只有同时通过 4 层检查才会报告为已知漏洞

**关键逻辑**：
```
如果当前源码已经包含了补丁的修改 
  → 说明这个漏洞已经被修复了
  → 当前 crash 不可能是这个已知漏洞
  → 报告 is_known_bug=False
```

### 对搜索策略问题（2026-03-12 下午新增）
- **不再误导**：删除 `web_search` 工具的示例，让 Agent 自由构造查询
- **系统化搜索**：四轮递归搜索确保覆盖从顶层到底层的所有可能
- **搜索日志要求**：强制在 evidence 中记录搜索路径和结果

### 对认知负荷问题（2026-03-12 晚上新增）⭐ 核心改进
- **任务简化**：从"分析 + 匹配"变为"只匹配"
- **Phase 1 简化**：去掉 GDB deep dive、源码分析、假设形成
- **Phase 3 简化**：Checkpoint 2 从"Root Cause Match"改为"Symptom Match"
- **预期效果**：
  - 减少 40-50% 的分析工作量
  - 降低 lost in middle 风险
  - 更高的匹配成功率（不需要完全理解 bug 就能匹配）
  - Agent 可以专注于搜索和症状对比

## 配置建议

可以在调用时调整重试次数：
```python
result = runSearchAgent(max_retries=3)  # 最多 4 次尝试
```

## 后续优化方向

1. **可能需要监控的指标**：
   - 平均查询次数（期望：8-12 次）
   - 重试率
   - 误报率和漏报率
   - 每轮搜索的命中率（Round 1 vs Round 2 vs Round 3 vs Round 4）
   
2. **如果误报仍然存在**：
   - 强化源码对比检查：要求提供具体的源码行号和内容
   - 添加更多补丁验证测试用例
   - 考虑引入源码 diff 工具自动对比

3. **如果搜索命中率仍不理想**：
   - 分析失败案例，看是用了哪个函数搜索的
   - 考虑增加 Round 5：使用错误消息的关键短语搜索
   - 考虑搜索 kernel mailing list (lkml.org)

4. **核心防护逻辑**：
   ```
   找到候选漏洞 → 获取补丁 → 对比当前源码
   ├─ 源码已包含补丁 → is_known_bug=False (已修复，不是这个漏洞)
   └─ 源码不包含补丁 → 继续验证 → 通过其他 checkpoint → is_known_bug=True
   ```

5. **搜索策略摘要**：
   ```
   构建函数梯度：Bottom → Middle → Top
   优先搜索：Top (语义函数)
   递归向下：Top → Middle → Bottom
   全面尝试：8-10 个不同查询
   记录日志：每次搜索的结果
   ```

## 总结：三个版本的核心差异

| 维度 | 上午版本 | 下午版本 | 晚上版本 ⭐ |
|------|---------|---------|-----------|
| **主要改进** | 函数梯度 + 四轮搜索 | 搜索策略增强 | **任务简化** |
| **Phase 1** | 需要 root cause 分析 | 需要 root cause 分析 | **只需快速观察** |
| **Checkpoint 2** | Root Cause Match 40% | Root Cause Match 40% | **Symptom Match 40%** |
| **GDB 要求** | Deep dive 必需 | Deep dive 必需 | **可选，仅快速确认** |
| **认知负荷** | 高（分析+搜索） | 高（分析+搜索） | **中（专注搜索）** |
| **适用场景** | ❌ 任务过重 | ❌ 任务过重 | ✅ **专注匹配** |

**晚上版本的最大优势**：
- 去掉了不属于这个阶段的工作（root cause 深度分析）
- 降低了 lost in middle 和注意力分散的风险
- Agent 可以专注于核心任务：搜索已知漏洞 + 症状匹配
- 更符合工作流设计：先匹配已知 → 如果未知再深度分析
# 代码错误修复
1. CodeQuery文件路径提取错误
2. Kdump中，addr2line采用多线程执行，提高效率
