from .tools import lookup_callgraph, lookup_symbol

CODEQUERY_TOOLS = {
    "Look up a function, struct, global variable, or macro definition": lookup_symbol,
    "Look up callers or callees for a function": lookup_callgraph,
}
