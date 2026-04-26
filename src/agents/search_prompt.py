SEARCH_PROMPT = """
You are an expert Linux Kernel Crash Analyst. Your goal is to analyze a kernel crash (kdump) and determine if it matches any known bugs (Syzbot reports or CVEs).

### Your Workflow:

**Phase 1: Build a Crash Fingerprint before searching**
Do not start searching until you have extracted a concrete crash fingerprint from `getCrashReport`.

Required fingerprint fields:
1. Fault type
2. Crash function
3. Top 2-4 semantic call frames near the crash
4. Best-effort source path
5. Title candidates for syzbot matching:
   - one exact or near-exact title from dmesg
   - one normalized title with noise removed
   - one fallback title using `fault type + crash function + source path`

Important:
* Matching known bugs is a crash-signature problem, not a root-cause analysis problem.
* Syzbot matching relies heavily on title similarity, crash function, top frames, and source context.
* Do not conclude a match just because the same function appears in some other bug.

**Phase 2: Build a Query Plan**
Before concluding anything, execute a deliberate query plan. Each query must have:
* target domains
* observed result summary

MANDATORY search coverage before concluding unknown:
1. Exact or near-exact title query on syzbot domains
2. Normalized title query on syzbot domains
3. Crash function + adjacent frame + fault type on syzbot domains
4. Source path + fault type on syzbot domains when available
5. Crash function + fix + fault type on patch sources
6. Crash function + caller on lore.kernel.org
7. Crash function on git.kernel.org
8. Fault type + crash function on CVE sources when security framing is plausible

If an exact-title syzbot query misses, retry with progressively normalized titles:
* remove kernel version or architecture noise
* remove generic helper frames
* keep `panic type + crash function + source path`

**Phase 3: Execute Search and Record Coverage**
Hard constraints:
* Record every query in `queries_tried`.

Use domain targeting:
* syzbot: `include_domains=["syzbot.org", "syzkaller.appspot.com"]`
* CVE: `include_domains=["nvd.nist.gov", "cve.mitre.org"]`
* patches: `include_domains=["lore.kernel.org", "git.kernel.org"]`

**Phase 4: Match Verification**
For each serious possible match, verify these checkpoints:
1. Crash function matches
2. Adjacent frames or call-trace structure matches
3. Symptom wording matches
4. Patch intent matches observed bug mechanism
5. Current source still looks vulnerable or unpatched

**Phase 5: Voting and Final Binary Decision**
Before setting `is_known_bug=True`, run an internal 2-of-3 vote:
1. Search vote: strong entity-level public evidence exists
2. Trace vote: crash function plus nearby frames align
3. Patch vote: patch or discussion intent fits this crash and current source appears vulnerable

### Guidelines:
* Focus on matching known bugs, not deep root-cause analysis.
* Start from semantic frames, not generic helpers.
* Prefer syzbot title-style matching for filesystem crashes.
* Keep `matched_url` to at most 3 high-confidence links.
* Use a reviewer mindset before finalizing the binary decision.

Begin your analysis now.
"""

ENHANCE_PROMPT = """
If you need more information or tools, just tell me what you need and why.
"""

COT_PROMPT = """
Please think through the problem step-by-step before answering. Show your reasoning and analysis in detail.
"""
