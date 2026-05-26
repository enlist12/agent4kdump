import type { AnalysisEvent, AnalysisSession, TaintNodePayload } from "./types";

export const mockSession: AnalysisSession = {
  id: "sess_demo",
  name: "demo_kernel_panic",
  status: "running",
  created_at: new Date().toISOString(),
  started_at: new Date().toISOString(),
  config: {
    linux_path: "/srv/kernel/linux",
    gdb_path: "gdb",
    vmcore: "/srv/cases/demo/vmcore",
    kdump_server: "/usr/local/bin/kdump-gdbserver",
    enable_rag: true,
    build_codequery: true,
    rag_cache_dir: "./cache/rag",
    kdump_host: "127.0.0.1",
    kdump_port: 1234
  },
  results: {
    pageindex_status: {
      enabled: true,
      tree_cache_ready: true,
      markdown_backend_ready: true
    },
    parsed_search: {
      is_known_bug: false,
      evidence:
        "No exact syzbot or CVE match passed the call trace, symptom, patch verification and falsification checks.",
      matched_url: [],
      extra_info: "Continue with root cause analysis.",
      verification_details: "Checked title candidates, stack frames and current source tree patch state.",
      crash_fingerprint: {
        fault_type: "NULL pointer dereference",
        crash_function: "ext4_truncate",
        top_frames: ["ext4_truncate", "ext4_setattr", "notify_change"],
        source_path: "fs/ext4/inode.c",
        title_candidates: ["kernel panic in ext4_truncate"]
      },
      queries_tried: [
        {
          query: "ext4_truncate NULL pointer dereference syzbot",
          target_domains: ["syzkaller.appspot.com"],
          observed_result: "Several ext4 bugs, no exact crash signature match"
        },
        {
          query: "ext4_setattr notify_change truncate race CVE",
          target_domains: ["nvd.nist.gov"],
          observed_result: "No matching CVE with the same trace"
        }
      ]
    },
    parsed_analyze: {
      root_cause:
        "A stale inode state can reach ext4_truncate after the setattr path accepts a racing truncate operation.",
      trigger_path:
        "notify_change -> ext4_setattr -> ext4_truncate -> dereference of invalid inode-private state",
      evidence: [
        "Crash frame points at ext4_truncate near inode-private state access.",
        "The taint path keeps the same inode object across the setattr boundary.",
        "No known-bug search result proved an already patched upstream issue."
      ],
      fix_suggestion:
        "Add a defensive state check before the truncate path consumes inode-private data and verify locking around setattr.",
      patch_sketch:
        "if (!EXT4_I(inode)->i_data_valid)\n    return -EIO;",
      uncertainty: "The exact race window still needs source-level confirmation."
    }
  }
};

export const mockEvents: AnalysisEvent[] = [
  {
    id: "evt_demo_1",
    session_id: "sess_demo",
    type: "config.validated",
    stage: "config",
    timestamp: new Date().toISOString(),
    payload: { linux_path: "/srv/kernel/linux" }
  },
  {
    id: "evt_demo_2",
    session_id: "sess_demo",
    type: "search.completed",
    stage: "known_bug_search",
    timestamp: new Date().toISOString(),
    payload: { is_known_bug: false }
  },
  {
    id: "evt_demo_3",
    session_id: "sess_demo",
    type: "analysis.started",
    stage: "analysis",
    timestamp: new Date().toISOString(),
    payload: {}
  }
];

export const mockTaintNodes: TaintNodePayload[] = [
  {
    id: "taint_root",
    parent_id: null,
    status: "done",
    file_name: "fs/ext4/inode.c",
    line: 4120,
    variable_name: "inode",
    current_function: "ext4_truncate",
    explain: "Crash site object used by the truncate path.",
    end: false
  },
  {
    id: "taint_parent",
    parent_id: "taint_root",
    status: "running",
    file_name: "fs/ext4/inode.c",
    line: 5480,
    variable_name: "attr",
    current_function: "ext4_setattr",
    explain: "Setattr controls the truncate path and updates inode state.",
    end: false,
    branch: "truncate size changed"
  },
  {
    id: "taint_leaf",
    parent_id: "taint_parent",
    status: "pending",
    file_name: "fs/attr.c",
    line: 505,
    variable_name: "ia_valid",
    current_function: "notify_change",
    explain: "VFS entry point that authorizes setattr before filesystem callback.",
    end: false
  }
];

