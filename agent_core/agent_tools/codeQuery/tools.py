from .codequery import get_proj_path
from langchain_core.tools import tool
from .codequery import get_func_def_codequery, get_struct_def_codequery, get_global_var_def_codequery, get_caller_codequery, get_callee_codequery
from .get_func_def import read_func, read_struct_def, read_global_var, read_func_first_line, read_marco
from typing import Annotated
import os
import json
import subprocess

def get_from_vmlinux(target: str, kind: str) -> dict|None:
    """
    Search for definition in vmlinux using GDB.
    Returns dict with keys: found, path, line, definition(content)
    """
    proj_path = get_proj_path()
    vmlinux_path = os.path.join(proj_path, "vmlinux")
    helper_path = os.path.join(os.path.dirname(__file__), "gdb_helper.py")
    
    if not os.path.exists(vmlinux_path):
        return None
        
    try:
        env = os.environ.copy()
        env["GDB_QUERY_TARGET"] = target
        env["GDB_QUERY_KIND"] = kind
        # Prefer ptype for structs as it is robust against missing file markers
        if kind == "struct":
            env["GDB_USE_PTYPE"] = "1"
        
        cmd = [
            "gdb", "-batch", "-n", 
            "-ex", f"file {vmlinux_path}",
            "-ex", f"source {helper_path}"
        ]
        
        # GDB might output other things, so we look for the JSON line
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            env=env,
            timeout=15 
        )
        
        for line in result.stdout.splitlines():
            if line.strip().startswith("{"):
                try:
                    data = json.loads(line)
                    if data.get("found"):
                        return data
                except:
                    continue
    except Exception:
        pass
    return None



@tool
def get_func_callback(
    func_names: Annotated[list[str], "List of function names to query"]
) -> Annotated[str, "Function definitions"]:
    """
    Retrieve the source code definitions for a list of functions.
    
    This tool searches the codebase for the definitions of the specified functions
    and returns their source code. It handles multiple definitions by prioritizing
    C source files over headers and using heuristics to find the actual implementation.
    
    Args:
        func_names (list[str]): A list of function names to look up (e.g., ["kmalloc", "vfs_read"])
        
    Returns:
        str: The source code definitions of the found functions, or "not found" messages.
    """
    response = ""
    for func_name in func_names:
        # First try to find exact definition using vmlinux if available
        # This resolves ambiguity in kernel sources (multiple archs/configs)
        # Use new generic helper for consistency, but keep func logic which needs simple location
        # Actually logic is slightly different, get_func_loc_from_vmlinux was simple info line
        # Let's switch to generic helper for verification.
        gdb_res = get_from_vmlinux(func_name, "function")
        if gdb_res and gdb_res.get("found"):
             if gdb_res.get("path") and gdb_res.get("line"):
                  file_path = gdb_res["path"]
                  line_no = gdb_res["line"]
                  full_path = os.path.join(get_proj_path(), file_path)
                  if os.path.exists(full_path):
                        func_def = read_func(file_path, 0, get_proj_path(), real_lineno=int(line_no))
                        if func_def:
                             response += f"Function {func_name} is defined as: \n```c\n{func_def}\n```\n"
                             continue

        func_loc = get_func_def_codequery(get_proj_path(), func_name)
        
        # heuristics: the definition of a function must NOT start with "\t"
        if func_loc and len(func_loc) > 0:
            func_loc_tmp = []
            for loc in func_loc:
                file_path, line_no = loc
                func_first_line = read_func_first_line(file_path, int(line_no), get_proj_path())
                if func_first_line and (not func_first_line.startswith("\t")):
                    func_loc_tmp.append(loc)
            func_loc = func_loc_tmp
        
        if not func_loc or len(func_loc) == 0:
            response += f"Function {func_name} is not found.\n"
            continue

        # example: [["source/xxx.c", "123"]]
        # for multiple function locations, firstly remove all ".h"
        if len(func_loc) > 1:
            # if there's at least one ".c" file:
            func_loc_tmp = [loc for loc in func_loc if loc[0].endswith(".c")]
            if len(func_loc_tmp) > 0:
                func_loc = func_loc_tmp
        


        # and let's use the last one
        # no, last one maybe not the best
        # TODO: better selection strategy
        file_path, line_no = func_loc[-1]

        # read the source code
        func_def = read_func(file_path, 0, get_proj_path(), real_lineno=int(line_no))
        response += f"Function {func_name} is defined as: \n```c\n{func_def}\n```\n"

    return response

@tool
def get_caller_callback(
    func_names: Annotated[list[str], "List of function names to query for callers"]
) -> Annotated[str, "Call sites of the functions"]:
    """
    Retrieve the call sites (callers) for a list of functions.
    
    Args:
        func_names (list[str]): A list of function names to look up.
        
    Returns:
        str: A list of file paths and line numbers where the functions are called.
    """
    response = ""
    for func_name in func_names:
        callers = get_caller_codequery(get_proj_path(), func_name)
        if not callers or len(callers) == 0:
            response += f"No callers found for {func_name}.\n"
            continue
            
        response += f"Callers of {func_name}:\n"
        # Limit to top 20 to avoid context overflow
        for loc in callers[:20]:
            file_path, line_no = loc
            # Try to read the code line
            try:
                code_line = read_func_first_line(file_path, int(line_no), get_proj_path())
                if code_line:
                    code_line = code_line.strip()
            except:
                code_line = ""
            
            response += f"  {file_path}:{line_no}  {code_line}\n"
        
        if len(callers) > 20:
            response += f"  ... and {len(callers) - 20} more.\n"
            
    return response

@tool
def get_callee_callback(
    func_names: Annotated[list[str], "List of function names to query for callees"]
) -> Annotated[str, "Functions called by the specified functions"]:
    """
    Retrieve the functions called by the specified functions (callees).
    
    Args:
        func_names (list[str]): A list of function names to look up.
        
    Returns:
        str: A list of file paths and line numbers where the called functions are defined.
    """
    response = ""
    for func_name in func_names:
        callees = get_callee_codequery(get_proj_path(), func_name)
        if not callees or len(callees) == 0:
            response += f"No callees found for {func_name}.\n"
            continue
            
        response += f"Functions called by {func_name}:\n"
        # Limit to top 20
        for loc in callees[:20]:
            file_path, line_no = loc
            try:
                code_line = read_func_first_line(file_path, int(line_no), get_proj_path())
                if code_line:
                    code_line = code_line.strip()
            except:
                code_line = ""
            response += f"  {file_path}:{line_no}  {code_line}\n"
            
        if len(callees) > 20:
            response += f"  ... and {len(callees) - 20} more.\n"
            
    return response

@tool
def get_struct_callback(
    struct_names: Annotated[list[str], "List of struct names to query"]
) -> Annotated[str, "Struct definitions"]:
    """
    Retrieve the source code definitions for a list of structures.
    
    This tool searches the codebase for the definitions of the specified C structures
    and returns their source code.
    
    Args:
        struct_names (list[str]): A list of struct names to look up (e.g., ["task_struct", "file"])
                                  Can optionally include "struct " prefix.
        
    Returns:
        str: The source code definitions of the found structures.
    """
    response = ""
    for struct_name in struct_names:
        if struct_name.startswith("struct "):
             query_name = struct_name
             struct_name = struct_name[7:] # keep clean name for display
        else:
             query_name = "struct " + struct_name

        # First try GDB/vmlinux for the most accurate definition (using ptype)
        gdb_res = get_from_vmlinux(query_name, "struct")
        if gdb_res and gdb_res.get("found"):
             if gdb_res.get("definition"):
                  # Ptype approach succeeded
                  response += f"Struct {struct_name} (from GDB ptype):\n```c\n{gdb_res['definition']}\n```\n"
                  continue
             elif gdb_res.get("path") and gdb_res.get("line"):
                  # Location approach succeeded (if enabled in helper later)
                  file_path = gdb_res["path"]
                  line_no = gdb_res["line"]
                  full_path = os.path.join(get_proj_path(), file_path)
                  if os.path.exists(full_path):
                        struct_def = read_struct_def(file_path, int(line_no), get_proj_path())
                        response += f"Struct {struct_name} is defined as: \n```c\n{struct_def}\n```\n"
                        continue

        # Fallback to text search
        struct_def = get_struct_def_codequery(get_proj_path(), struct_name)
        if not struct_def or len(struct_def) == 0:
            response += f"Struct {struct_name} is not found.\n"
            continue

        # and let's use the last one
        file_path, line_no = struct_def[-1]

        # read the source code
        # struct_def = read_func(file_path, 0, proj_path, real_lineno=int(line_no))
        struct_def = read_struct_def(file_path, int(line_no), get_proj_path())
        response += f"Struct {struct_name} is defined as: \n```c\n{struct_def}\n```\n"
    return response

def _is_macro_def(arg):
    return arg.isupper()

@tool
def get_global_var(
    var_names: Annotated[list[str], "List of global variable or macro names to query"]
) -> Annotated[str, "Global variable/macro definitions"]:
    """
    Retrieve the definitions of global variables or macros.
    
    This tool searches for global variables or preprocessor macros in the codebase.
    It automatically detects macros based on uppercase naming convention.
    
    Args:
        var_names (list[str]): A list of variable or macro names to look up.
        
    Returns:
        str: The source code definitions of the found variables or macros.
    """
    response = ""
    for var_name in var_names:
        if not var_name:
            response += "Error: empty variable name.\n"
            continue
        
        if _is_macro_def(var_name):
            var_def_loc = get_global_var_def_codequery(get_proj_path(), var_name, is_marco=True)
            if var_def_loc:
                # and let's use the last one
                file_path, line_no = var_def_loc[-1]

                # read the source code
                var_def = read_marco(file_path, int(line_no), get_proj_path())
                response += f"{var_name} is defined as: \n```c\n{var_def}\n```\n"
                continue
        var_def_loc = get_global_var_def_codequery(get_proj_path(), var_name) 
        if not var_def_loc:
            response += f"{var_name} is not found.\n"
            continue
            

        # and let's use the last one
        file_path, line_no = var_def_loc[-1]

        # read the source code
        if _is_macro_def(var_name):
            var_def = read_marco(file_path, int(line_no), get_proj_path())
        else:
            var_def = read_global_var(file_path, int(line_no), get_proj_path())
        response += f"Global variable {var_name} is defined as: \n```c\n{var_def}\n```\n"
    return response

def test_code_query_tools():
    """
    Test suite for CodeQuery tools.
    Targets kernel source in /root/agent4kdump/kernel/linux
    """
    print("Starting CodeQuery tests...")
    # Import locally to avoid circular dependency issues at top level if any
    try:
        from .codequery import set_proj_path
    except ImportError:
         print("⚠️ Could not import set_proj_path from .codequery")
         return
    
    KERNEL_DIR = "/root/agent4kdump/kernel/linux"
    
    # 1. Setup project path
    print(f"\n[Setup] Setting project path to {KERNEL_DIR}")
    try:
        set_proj_path(KERNEL_DIR)
    except Exception as e:
        print(f"❌ Failed to set project path: {e}")
        return

    # 2. Test get_func_callback
    print("\n[Test] get_func_callback: vfs_read")
    try:
        # vfs_read is a common kernel function call
        result = get_func_callback.func(["vfs_read"])
        if "not found" in result:
             print(f"⚠️ vfs_read not found: {result}")
        else:
             print("vfs_read definition found.")
             print(f"Snippet: {result[:200]}...")
    except Exception as e:
        print(f"❌ Exception in get_func_callback: {e}")

    # 3. Test get_struct_callback
    print("\n[Test] get_struct_callback: cred")
    try:
        # struct cred is a fundamental kernel structure
        result = get_struct_callback.func(["cred"])
        if "not found" in result:
             print(f"⚠️ struct cred not found: {result}")
        else:
             print("struct cred definition found.")
             print(f"Snippet: {result[:200]}...")
    except Exception as e:
        print(f"❌ Exception in get_struct_callback: {e}")

    # 4. Test get_global_var
    print("\n[Test] get_global_var: jiffies")
    try:
        # jiffies is a well-known global variable
        result = get_global_var.func(["jiffies"])
        if "not found" in result:
             print(f"⚠️ jiffies not found: {result}")
        else:
             print("jiffies definition found.")
             print(f"Snippet: {result[:200]}...")
    except Exception as e:
        print(f"❌ Exception in get_global_var: {e}")

    print("\nCodeQuery tests completed.")