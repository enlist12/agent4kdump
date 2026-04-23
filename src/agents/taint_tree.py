from typing import Any, Callable, Dict, List, Literal, Optional
from uuid import uuid4

from langchain_core.messages import AnyMessage
from pydantic import BaseModel, Field

from .schemas import TaintAnalysisObj, TaintBranch, TaintStepResult


class MessageCheckpoint(BaseModel):
    """Record a reusable point in message history."""

    checkpoint_id: str
    thread_id: str = "taint-tree"
    checkpoint_ns: str = ""
    parent_id: Optional[str] = None
    step: int = 0
    message_count: int = 0
    summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MessageMemory:
    """Store branch-isolated message deltas by checkpoint."""

    def __init__(self, thread_id: str = "taint-tree") -> None:
        self.thread_id = thread_id
        self.checkpoints: Dict[str, MessageCheckpoint] = {}
        self._deltas: Dict[str, List[AnyMessage]] = {}
        self._history: Dict[str, List[str]] = {}

    def create_checkpoint(
        self,
        messages: List[AnyMessage],
        parent_id: Optional[str] = None,
        summary: Optional[str] = None,
        checkpoint_ns: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a checkpoint from message deltas."""
        checkpoint_id = self._new_id("msg")
        parent = self.checkpoints.get(parent_id) if parent_id else None
        thread_id = parent.thread_id if parent else self.thread_id
        namespace = checkpoint_ns or (parent.checkpoint_ns if parent else "")
        step = parent.step + 1 if parent else 0
        message_count = (parent.message_count if parent else 0) + len(messages)
        self.checkpoints[checkpoint_id] = MessageCheckpoint(
            checkpoint_id=checkpoint_id,
            thread_id=thread_id,
            checkpoint_ns=namespace,
            parent_id=parent_id,
            step=step,
            message_count=message_count,
            summary=summary if summary is not None else (parent.summary if parent else None),
            metadata=metadata or {},
        )
        self._deltas[checkpoint_id] = list(messages)
        self._history.setdefault(thread_id, []).append(checkpoint_id)
        return checkpoint_id

    def fork_checkpoint(self, checkpoint_id: str, checkpoint_ns: str = "") -> str:
        """Create an isolated branch checkpoint from an existing checkpoint."""
        return self.create_checkpoint(
            [],
            parent_id=checkpoint_id,
            checkpoint_ns=checkpoint_ns,
            metadata={"forked_from": checkpoint_id},
        )

    def restore(self, checkpoint_id: str) -> List[AnyMessage]:
        """Return messages visible at a checkpoint."""
        messages: List[AnyMessage] = []
        chain: List[str] = []
        current_id: Optional[str] = checkpoint_id
        while current_id:
            chain.append(current_id)
            current_id = self.checkpoints[current_id].parent_id
        for item_id in reversed(chain):
            messages.extend(self._deltas.get(item_id, []))
        return messages

    def append(self, checkpoint_id: str, new_messages: List[AnyMessage]) -> str:
        """Append messages to a checkpoint and return the new checkpoint id."""
        return self.create_checkpoint(new_messages, parent_id=checkpoint_id)

    def get_config(self, checkpoint_id: str) -> Dict[str, Dict[str, str]]:
        """Return a LangChain-style configurable checkpoint reference."""
        checkpoint = self.checkpoints[checkpoint_id]
        return {
            "configurable": {
                "thread_id": checkpoint.thread_id,
                "checkpoint_ns": checkpoint.checkpoint_ns,
                "checkpoint_id": checkpoint.checkpoint_id,
            }
        }

    def get_state(self, checkpoint_id: str) -> Dict[str, Any]:
        """Return checkpoint state with materialized messages."""
        checkpoint = self.checkpoints[checkpoint_id]
        return {
            "checkpoint": checkpoint,
            "messages": self.restore(checkpoint_id),
            "config": self.get_config(checkpoint_id),
        }

    def get_state_history(self, thread_id: Optional[str] = None) -> List[MessageCheckpoint]:
        """Return checkpoint history for a thread."""
        target_thread = thread_id or self.thread_id
        return [
            self.checkpoints[item_id]
            for item_id in self._history.get(target_thread, [])
            if item_id in self.checkpoints
        ]

    def summarize_if_needed(self, checkpoint_id: str) -> str:
        """Return the checkpoint unchanged until compaction is implemented."""
        return checkpoint_id

    @staticmethod
    def _new_id(prefix: str) -> str:
        """Create a short unique id for memory records."""
        return f"{prefix}_{uuid4().hex[:12]}"


class TaintTreeNode(BaseModel):
    """Represent one taint node and its message checkpoint."""

    node_id: str
    parent_id: Optional[str] = None
    taint_obj: Optional[TaintAnalysisObj] = None
    checkpoint_id: str
    branch: Optional[TaintBranch] = None
    children: List[str] = Field(default_factory=list)
    status: Literal["pending", "running", "done", "failed", "pruned"] = "pending"
    error: Optional[str] = None


class TaintTree:
    """Manage taint-analysis branch nodes and traversal state."""

    def __init__(self) -> None:
        self.root_id: Optional[str] = None
        self.current_node_id: Optional[str] = None
        self.nodes: Dict[str, TaintTreeNode] = {}

    def create_root(self, taint_obj: TaintAnalysisObj, checkpoint_id: str) -> TaintTreeNode:
        """Create the root taint node."""
        node = TaintTreeNode(
            node_id=self._new_id("taint"),
            taint_obj=taint_obj,
            checkpoint_id=checkpoint_id,
        )
        self.root_id = node.node_id
        self.current_node_id = node.node_id
        self.nodes[node.node_id] = node
        return node

    def add_child(
        self,
        parent_id: str,
        taint_obj: Optional[TaintAnalysisObj],
        checkpoint_id: str,
        branch: Optional[TaintBranch] = None,
    ) -> TaintTreeNode:
        """Add a child node under a parent node."""
        node = TaintTreeNode(
            node_id=self._new_id("taint"),
            parent_id=parent_id,
            taint_obj=taint_obj,
            checkpoint_id=checkpoint_id,
            branch=branch,
        )
        self.nodes[node.node_id] = node
        self.nodes[parent_id].children.append(node.node_id)
        return node

    def get_node(self, node_id: str) -> TaintTreeNode:
        """Return a tree node by id."""
        return self.nodes[node_id]

    def mark_done(self, node_id: str) -> None:
        """Mark a node as completed."""
        self.nodes[node_id].status = "done"

    def mark_pruned(self, node_id: str, reason: str) -> None:
        """Mark a node as intentionally skipped."""
        node = self.nodes[node_id]
        node.status = "pruned"
        node.error = reason

    def mark_failed(self, node_id: str, reason: str) -> None:
        """Mark a node as failed."""
        node = self.nodes[node_id]
        node.status = "failed"
        node.error = reason

    def get_path(self, node_id: str) -> List[TaintTreeNode]:
        """Return the path from root to a node."""
        path: List[TaintTreeNode] = []
        current_id: Optional[str] = node_id
        while current_id:
            node = self.nodes[current_id]
            path.append(node)
            current_id = node.parent_id
        path.reverse()
        return path

    def path_objects(self, node_id: str) -> List[TaintAnalysisObj]:
        """Return unique taint objects on the path to a node."""
        objects: List[TaintAnalysisObj] = []
        for node in self.get_path(node_id):
            if node.taint_obj is None:
                continue
            if objects and node.taint_obj.same_target(objects[-1]):
                continue
            objects.append(node.taint_obj)
        return objects

    def format_history(self, node_id: str) -> str:
        """Format one path with branch assumptions for prompting."""
        lines: List[str] = []
        step = 1
        last_obj: Optional[TaintAnalysisObj] = None
        for node in self.get_path(node_id):
            if node.branch:
                lines.append(
                    "Branch: "
                    f"condition={node.branch.condition}; "
                    f"assumption={node.branch.assumption}; "
                    f"reason={node.branch.reason}"
                )
            if node.taint_obj is None:
                continue
            if last_obj and node.taint_obj.same_target(last_obj):
                continue
            lines.append(f"Step {step}: {node.taint_obj.get_prompt()}")
            last_obj = node.taint_obj
            step += 1
        return "\n".join(lines) or "No structured taint path available."

    def branch_depth(self, node_id: str) -> int:
        """Return how many branch assumptions exist on the path."""
        return sum(1 for node in self.get_path(node_id) if node.branch is not None)

    def has_seen_target(self, node_id: str, taint_obj: TaintAnalysisObj) -> bool:
        """Return whether a taint object already appears on the node path."""
        for node in self.get_path(node_id):
            if node.taint_obj and node.taint_obj.same_target(taint_obj):
                return True
        return False

    def primary_path(self) -> List[TaintAnalysisObj]:
        """Return the first completed path as a linear taint chain."""
        leaves = [node for node in self.nodes.values() if not node.children]
        leaves.sort(key=lambda item: item.node_id)
        if not leaves:
            return []
        objects: List[TaintAnalysisObj] = []
        for node in self.get_path(leaves[0].node_id):
            if node.taint_obj is None:
                continue
            if objects and node.taint_obj.same_target(objects[-1]):
                continue
            objects.append(node.taint_obj)
        return objects

    def describe(self) -> str:
        """Build a compact text summary of all tree branches."""
        lines: List[str] = []
        for node in self.nodes.values():
            path = self.get_path(node.node_id)
            depth = max(len(path) - 1, 0)
            prefix = "  " * depth
            branch = ""
            if node.branch:
                branch = f" branch={node.branch.label} assumption={node.branch.assumption};"
            obj = node.taint_obj.get_prompt() if node.taint_obj else "no taint object"
            error = f" note={node.error}" if node.error else ""
            lines.append(f"{prefix}- {node.node_id}: status={node.status};{branch} {obj}{error}")
        return "\n".join(lines)

    @staticmethod
    def _new_id(prefix: str) -> str:
        """Create a short unique id for tree nodes."""
        return f"{prefix}_{uuid4().hex[:12]}"


class TaintTreeRunner:
    """Execute taint-tree DFS while delegating agent-specific steps via callbacks."""

    def __init__(
        self,
        max_taint_steps: int,
        max_tree_nodes: int,
        max_branch_depth: int,
        analyze_node: Callable[
            [TaintTree, MessageMemory, TaintTreeNode],
            tuple[Optional[TaintStepResult], List[AnyMessage], str],
        ],
        build_warning: Callable[[str, str], AnyMessage],
        build_branch_message: Callable[[TaintBranch], AnyMessage],
        prepare_next_obj: Callable[[TaintAnalysisObj], None],
        join_text: Callable[..., Optional[str]],
        max_branch_children: int = 3,
    ) -> None:
        self.max_taint_steps = max_taint_steps
        self.max_tree_nodes = max_tree_nodes
        self.max_branch_depth = max_branch_depth
        self.max_branch_children = max_branch_children
        self.analyze_node = analyze_node
        self.build_warning = build_warning
        self.build_branch_message = build_branch_message
        self.prepare_next_obj = prepare_next_obj
        self.join_text = join_text

    def run(
        self,
        root_obj: TaintAnalysisObj,
        messages: List[AnyMessage],
    ) -> tuple[List[TaintAnalysisObj], List[AnyMessage], str]:
        memory = MessageMemory()
        tree = TaintTree()
        root_checkpoint = memory.create_checkpoint(messages)
        root = tree.create_root(root_obj, root_checkpoint)
        stack = [root.node_id]
        collected_messages: List[AnyMessage] = []
        primary_path: List[TaintAnalysisObj] = []

        while stack:
            node = tree.get_node(stack.pop())
            tree.current_node_id = node.node_id
            node.status = "running"

            if len(tree.nodes) > self.max_tree_nodes:
                tree.mark_pruned(
                    node.node_id,
                    f"Reached max_tree_nodes={self.max_tree_nodes}.",
                )
                continue

            path_objs = tree.path_objects(node.node_id)
            if node.taint_obj is None:
                tree.mark_failed(node.node_id, "Missing taint object.")
                continue

            if node.taint_obj.end:
                tree.mark_done(node.node_id)
                if not primary_path:
                    primary_path = path_objs
                continue

            if len(path_objs) - 1 >= self.max_taint_steps:
                self._append_warning(
                    memory,
                    node,
                    collected_messages,
                    "taint_tree",
                    f"Reached max_taint_steps={self.max_taint_steps}.",
                )
                tree.mark_done(node.node_id)
                if not primary_path:
                    primary_path = path_objs
                continue

            step_result, delta_messages, warning = self.analyze_node(
                tree,
                memory,
                node,
            )
            collected_messages.extend(delta_messages)
            node.checkpoint_id = memory.append(node.checkpoint_id, delta_messages)

            if warning:
                warning_msg = self.build_warning("taint_analysis", warning)
                collected_messages.append(warning_msg)
                node.checkpoint_id = memory.append(node.checkpoint_id, [warning_msg])

            if step_result is None:
                self._append_warning(
                    memory,
                    node,
                    collected_messages,
                    "taint_tree",
                    "Taint agent did not return a structured step result.",
                )
                tree.mark_failed(node.node_id, "Missing structured taint step.")
                if not primary_path:
                    primary_path = path_objs
                continue

            if step_result.kind == "terminal":
                if step_result.terminal_reason:
                    node.taint_obj.end = True
                    node.taint_obj.explain = self.join_text(
                        node.taint_obj.explain,
                        f"Stop: {step_result.terminal_reason}",
                    )
                tree.mark_done(node.node_id)
                if not primary_path:
                    primary_path = path_objs
                continue

            if step_result.kind == "single":
                child = self._create_single_child(tree, memory, node, step_result)
                if child is None:
                    self._append_warning(
                        memory,
                        node,
                        collected_messages,
                        "taint_tree",
                        "Single-step result did not include next_obj.",
                    )
                    tree.mark_failed(node.node_id, "Missing next_obj.")
                    if not primary_path:
                        primary_path = path_objs
                    continue
                tree.mark_done(node.node_id)
                stack.append(child.node_id)
                continue

            children = self._create_branch_children(
                tree,
                memory,
                node,
                step_result,
                collected_messages,
            )
            if not children:
                self._append_warning(
                    memory,
                    node,
                    collected_messages,
                    "taint_tree",
                    "Branch-step result did not include analyzable branches.",
                )
                tree.mark_failed(node.node_id, "Missing branch children.")
                if not primary_path:
                    primary_path = path_objs
                continue

            tree.mark_done(node.node_id)
            for child in reversed(children):
                stack.append(child.node_id)

        if not primary_path:
            primary_path = tree.primary_path() or [root_obj]
        return primary_path, collected_messages, tree.describe()

    def _create_single_child(
        self,
        tree: TaintTree,
        memory: MessageMemory,
        node: TaintTreeNode,
        step_result: TaintStepResult,
    ) -> Optional[TaintTreeNode]:
        next_obj = step_result.next_obj
        if next_obj is None:
            return None
        self.prepare_next_obj(next_obj)
        if tree.has_seen_target(node.node_id, next_obj):
            next_obj.end = True
            next_obj.explain = self.join_text(
                next_obj.explain,
                "Stop: tracing converged to a previously visited object.",
            )
        checkpoint_id = memory.summarize_if_needed(node.checkpoint_id)
        return tree.add_child(node.node_id, next_obj, checkpoint_id)

    def _create_branch_children(
        self,
        tree: TaintTree,
        memory: MessageMemory,
        node: TaintTreeNode,
        step_result: TaintStepResult,
        collected_messages: List[AnyMessage],
    ) -> List[TaintTreeNode]:
        if tree.branch_depth(node.node_id) >= self.max_branch_depth:
            return []
        capacity = max(self.max_tree_nodes - len(tree.nodes), 0)
        branches = sorted(step_result.branches, key=lambda item: item.priority)
        branches = branches[: min(self.max_branch_children, capacity)]
        children: List[TaintTreeNode] = []
        for branch in branches:
            checkpoint_id = memory.fork_checkpoint(
                node.checkpoint_id,
                checkpoint_ns=f"branch:{branch.label}",
            )
            branch_message = self.build_branch_message(branch)
            checkpoint_id = memory.append(checkpoint_id, [branch_message])
            collected_messages.append(branch_message)
            child = tree.add_child(
                node.node_id,
                node.taint_obj,
                checkpoint_id,
                branch,
            )
            children.append(child)
        return children

    def _append_warning(
        self,
        memory: MessageMemory,
        node: TaintTreeNode,
        collected_messages: List[AnyMessage],
        step: str,
        reason: str,
    ) -> None:
        warning_msg = self.build_warning(step, reason)
        collected_messages.append(warning_msg)
        node.checkpoint_id = memory.append(node.checkpoint_id, [warning_msg])
