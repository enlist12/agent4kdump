from .tools import get_callee_callback, get_caller_callback, get_func_callback, get_struct_callback, get_global_var

CODEQUERY_TOOLS = {
    "Retrieve the functions that call the specified functions (callers)": get_caller_callback,
    "Retrieve the functions called by the specified functions (callees)": get_callee_callback,
    "Retrieve the definition and code of the specified functions": get_func_callback,
    "Retrieve the definition and fields of the specified structures": get_struct_callback,
    "Retrieve the definition and value of the specified global variables": get_global_var,
}