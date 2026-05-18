from dataclasses import dataclass, field
from typing import Callable, Literal, Optional
from uuid import uuid4

from langchain_core.messages import AnyMessage

from .schemas import TaintAnalysisObj, TaintBranch, TaintStepResult


class MessageMemory:
    """Checkpoint message history so each branch can restore its own context."""

    def __init__(self) -> None:
        self.parents: dict[str, Optional[str]] = {}
        self.deltas: dict[str, list[AnyMessage]] = {}

    def create_checkpoint(
        self,
        messages: list[AnyMessage],
        parent_id: Optional[str] = None,
        checkpoint_ns: str = "",
    ) -> str:
        checkpoint_id = self._new_id("msg")
        self.parents[checkpoint_id] = parent_id
        self.deltas[checkpoint_id] = list(messages)
        return checkpoint_id

    def fork_checkpoint(self, checkpoint_id: str, checkpoint_ns: str = "") -> str:
        return self.create_checkpoint([], parent_id=checkpoint_id, checkpoint_ns=checkpoint_ns)

    def append(self, checkpoint_id: str, messages: list[AnyMessage]) -> str:
        return self.create_checkpoint(messages, parent_id=checkpoint_id)

    def restore(self, checkpoint_id: str) -> list[AnyMessage]:
        chain: list[str] = []
        while checkpoint_id:
            chain.append(checkpoint_id)
            checkpoint_id = self.parents.get(checkpoint_id)
        return [message for item in reversed(chain) for message in self.deltas.get(item, [])]

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class TaintTreeNode:
    node_id: str
    checkpoint_id: str
    parent_id: Optional[str] = None
    taint_obj: Optional[TaintAnalysisObj] = None
    branch: Optional[TaintBranch] = None
    children: list[str] = field(default_factory=list)
    status: Literal["pending", "running", "done", "failed", "pruned"] = "pending"
    error: Optional[str] = None
    sequence: int = 0


class TaintTree:
    """Manage taint-analysis branches and select a primary result path."""

    def __init__(self) -> None:
        self.root_id: Optional[str] = None
        self.current_node_id: Optional[str] = None
        self.nodes: dict[str, TaintTreeNode] = {}
        self._sequence = 0

    def create_root(self, taint_obj: TaintAnalysisObj, checkpoint_id: str) -> TaintTreeNode:
        node = self._new_node(checkpoint_id=checkpoint_id, taint_obj=taint_obj)
        self.root_id = self.current_node_id = node.node_id
        return node

    def add_child(
        self,
        parent_id: str,
        taint_obj: Optional[TaintAnalysisObj],
        checkpoint_id: str,
        branch: Optional[TaintBranch] = None,
    ) -> TaintTreeNode:
        node = self._new_node(parent_id, checkpoint_id, taint_obj, branch)
        self.nodes[parent_id].children.append(node.node_id)
        return node

    def get_node(self, node_id: str) -> TaintTreeNode:
        return self.nodes[node_id]

    def mark(self, node_id: str, status: str, error: Optional[str] = None) -> None:
        node = self.nodes[node_id]
        node.status = status
        node.error = error or node.error

    def get_path(self, node_id: str) -> list[TaintTreeNode]:
        path: list[TaintTreeNode] = []
        while node_id:
            node = self.nodes[node_id]
            path.append(node)
            node_id = node.parent_id
        return list(reversed(path))

    def path_objects(self, node_id: str) -> list[TaintAnalysisObj]:
        objects: list[TaintAnalysisObj] = []
        for node in self.get_path(node_id):
            if not node.taint_obj:
                continue
            if objects and node.taint_obj.same_target(objects[-1]):
                objects[-1] = node.taint_obj
            else:
                objects.append(node.taint_obj)
        return objects

    def format_history(self, node_id: str) -> str:
        lines: list[str] = []
        last_obj: Optional[TaintAnalysisObj] = None
        last_obj_line: Optional[int] = None
        step = 1
        for node in self.get_path(node_id):
            if node.branch:
                lines.append(
                    "Branch: "
                    f"condition={node.branch.condition}; "
                    f"assumption={node.branch.assumption}; "
                    f"reason={node.branch.reason}"
                )
            if not node.taint_obj:
                continue
            line = f"Step {step}: {node.taint_obj.get_prompt()}"
            if last_obj and node.taint_obj.same_target(last_obj):
                if last_obj_line is not None:
                    lines[last_obj_line] = f"Step {step - 1}: {node.taint_obj.get_prompt()}"
            else:
                last_obj_line = len(lines)
                lines.append(line)
                step += 1
            last_obj = node.taint_obj
        return "\n".join(lines) or "No structured taint path available."

    def branch_depth(self, node_id: str) -> int:
        return sum(node.branch is not None for node in self.get_path(node_id))

    def has_seen_target(self, node_id: str, taint_obj: TaintAnalysisObj) -> bool:
        return any(
            node.taint_obj and node.taint_obj.same_target(taint_obj)
            for node in self.get_path(node_id)
        )

    def primary_leaf_id(self) -> Optional[str]:
        leaves = [node for node in self.nodes.values() if not node.children]
        if not leaves:
            return None

        score = {"done": 3, "running": 2, "failed": 1, "pruned": 0}

        def key(node: TaintTreeNode) -> tuple:
            path_objects = self.path_objects(node.node_id)
            branch_rank = tuple(
                item.branch.priority for item in self.get_path(node.node_id) if item.branch
            )
            return (
                -score.get(node.status, 0),
                -int(bool(path_objects and path_objects[-1].end)),
                -len(path_objects),
                branch_rank,
                node.sequence,
            )

        return min(leaves, key=key).node_id

    def primary_path(self) -> list[TaintAnalysisObj]:
        leaf_id = self.primary_leaf_id()
        return self.path_objects(leaf_id) if leaf_id else []

    def describe(self) -> str:
        lines: list[str] = []
        for node in self.nodes.values():
            prefix = "  " * max(len(self.get_path(node.node_id)) - 1, 0)
            branch = (
                f" branch={node.branch.label} assumption={node.branch.assumption};"
                if node.branch
                else ""
            )
            obj = node.taint_obj.get_prompt() if node.taint_obj else "no taint object"
            note = f" note={node.error}" if node.error else ""
            lines.append(f"{prefix}- {node.node_id}: status={node.status};{branch} {obj}{note}")
        return "\n".join(lines)

    def _new_node(
        self,
        parent_id: Optional[str] = None,
        checkpoint_id: str = "",
        taint_obj: Optional[TaintAnalysisObj] = None,
        branch: Optional[TaintBranch] = None,
    ) -> TaintTreeNode:
        self._sequence += 1
        node = TaintTreeNode(
            node_id=f"taint_{uuid4().hex[:12]}",
            parent_id=parent_id,
            taint_obj=taint_obj,
            checkpoint_id=checkpoint_id,
            branch=branch,
            sequence=self._sequence,
        )
        self.nodes[node.node_id] = node
        return node


class TaintTreeRunner:
    """Run DFS taint analysis across conditional branches."""

    def __init__(
        self,
        max_taint_steps: int,
        max_tree_nodes: int,
        max_branch_depth: int,
        analyze_node: Callable[
            [TaintTree, MessageMemory, TaintTreeNode],
            tuple[Optional[TaintStepResult], list[AnyMessage], str],
        ],
        build_warning: Callable[[str, str], AnyMessage],
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
        self.prepare_next_obj = prepare_next_obj
        self.join_text = join_text

    def run(
        self,
        root_obj: TaintAnalysisObj,
        messages: list[AnyMessage],
    ) -> tuple[list[TaintAnalysisObj], list[AnyMessage], str]:
        memory = MessageMemory()
        tree = TaintTree()
        root = tree.create_root(root_obj, memory.create_checkpoint(messages))
        stack = [root.node_id]

        while stack:
            node = tree.get_node(stack.pop())
            tree.current_node_id = node.node_id
            node.status = "running"

            path_objs = tree.path_objects(node.node_id)
            if not node.taint_obj:
                tree.mark(node.node_id, "failed", "Missing taint object.")
            elif len(tree.nodes) > self.max_tree_nodes:
                tree.mark(node.node_id, "pruned", f"Reached max_tree_nodes={self.max_tree_nodes}.")
            elif node.taint_obj.end:
                tree.mark(node.node_id, "done")
            elif len(path_objs) - 1 >= self.max_taint_steps:
                self._warn(memory, node, "taint_tree", f"Reached max_taint_steps={self.max_taint_steps}.")
                tree.mark(node.node_id, "done")
            else:
                stack.extend(reversed(self._expand_node(tree, memory, node)))

        leaf_id = tree.primary_leaf_id()
        primary_path = tree.path_objects(leaf_id) if leaf_id else [root_obj]
        primary_messages = memory.restore(tree.get_node(leaf_id).checkpoint_id)[len(messages) :] if leaf_id else []
        return primary_path, primary_messages, tree.describe()

    def _expand_node(
        self,
        tree: TaintTree,
        memory: MessageMemory,
        node: TaintTreeNode,
    ) -> list[str]:
        result, delta_messages, warning = self.analyze_node(tree, memory, node)
        node.checkpoint_id = memory.append(node.checkpoint_id, delta_messages)
        if warning:
            self._warn(memory, node, "taint_analysis", warning)

        if result is None:
            self._warn(memory, node, "taint_tree", "Taint agent did not return a structured step result.")
            tree.mark(node.node_id, "failed", "Missing structured taint step.")
            return []
        if result.kind == "terminal":
            self._mark_terminal(tree, node, result.terminal_reason)
            return []
        if len(tree.nodes) >= self.max_tree_nodes:
            self._warn(memory, node, "taint_tree", f"Reached max_tree_nodes={self.max_tree_nodes}.")
            tree.mark(node.node_id, "done")
            return []

        children = self._single_child(tree, node, result) if result.kind == "single" else self._branch_children(tree, memory, node, result)
        if children:
            tree.mark(node.node_id, "done")
            return [child.node_id for child in children]

        reason = "Missing next_obj." if result.kind == "single" else "Missing branch children."
        self._warn(memory, node, "taint_tree", reason)
        tree.mark(node.node_id, "failed", reason)
        return []

    def _mark_terminal(
        self,
        tree: TaintTree,
        node: TaintTreeNode,
        reason: Optional[str],
    ) -> None:
        if reason and node.taint_obj:
            node.taint_obj.end = True
            node.taint_obj.explain = self.join_text(node.taint_obj.explain, f"Stop: {reason}")
        tree.mark(node.node_id, "done")

    def _single_child(
        self,
        tree: TaintTree,
        node: TaintTreeNode,
        result: TaintStepResult,
    ) -> list[TaintTreeNode]:
        if not result.next_obj:
            return []
        next_obj = result.next_obj
        self.prepare_next_obj(next_obj)
        if tree.has_seen_target(node.node_id, next_obj):
            next_obj.end = True
            next_obj.explain = self.join_text(
                next_obj.explain,
                "Stop: tracing converged to a previously visited object.",
            )
        return [tree.add_child(node.node_id, next_obj, node.checkpoint_id)]

    def _branch_children(
        self,
        tree: TaintTree,
        memory: MessageMemory,
        node: TaintTreeNode,
        result: TaintStepResult,
    ) -> list[TaintTreeNode]:
        if tree.branch_depth(node.node_id) >= self.max_branch_depth:
            return []
        capacity = self.max_tree_nodes - len(tree.nodes)
        branches = sorted(result.branches, key=lambda item: item.priority)[: self.max_branch_children]
        children: list[TaintTreeNode] = []
        for branch in branches[:capacity]:
            checkpoint_id = memory.fork_checkpoint(node.checkpoint_id)
            taint_obj = node.taint_obj.model_copy(deep=True) if node.taint_obj else None
            children.append(tree.add_child(node.node_id, taint_obj, checkpoint_id, branch))
        return children

    def _warn(self, memory: MessageMemory, node: TaintTreeNode, step: str, reason: str) -> None:
        node.error = reason
        node.checkpoint_id = memory.append(node.checkpoint_id, [self.build_warning(step, reason)])
