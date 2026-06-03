import { useMemo } from "react";
import ReactFlow, { Background, Controls, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";
import type { TaintNodePayload } from "../../api/types";
import { TaintNode } from "./TaintNode";

const nodeTypes = {
  taintNode: TaintNode
};

export function TaintFlowGraph({ nodes }: { nodes: TaintNodePayload[] }) {
  const graph = useMemo(() => {
    const flowNodes: Node<TaintNodePayload>[] = nodes.map((node, index) => ({
      id: node.id,
      type: "taintNode",
      position: {
        x: (index % 2) * 340 + 80,
        y: Math.floor(index / 2) * 180 + 60
      },
      data: node
    }));

    const edges: Edge[] = nodes
      .filter((node) => node.parent_id)
      .map((node) => ({
        id: `${node.parent_id}-${node.id}`,
        source: node.parent_id as string,
        target: node.id,
        animated: node.status === "running",
        style: { stroke: "#2563eb" }
      }));

    return { flowNodes, edges };
  }, [nodes]);

  return (
    <div className="h-full bg-slate-950">
      {nodes.length ? (
        <ReactFlow
          nodes={graph.flowNodes}
          edges={graph.edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
        >
          <Background color="#1e293b" gap={20} />
          <Controls className="!border-slate-700 !bg-slate-900 !text-slate-200" />
        </ReactFlow>
      ) : (
        <div className="flex h-full items-center justify-center p-8 text-sm text-slate-500">
          No taint tree has been emitted for this session yet.
        </div>
      )}
    </div>
  );
}
