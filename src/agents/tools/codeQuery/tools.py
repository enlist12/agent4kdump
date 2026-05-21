from .codequery import get_proj_path
from .codequery import (
    get_func_def_codequery,
    get_struct_def_codequery,
    get_global_var_def_codequery,
    get_caller_codequery,
    get_callee_codequery,
)
from .get_func_def import (
    read_func,
    read_struct_def,
    read_global_var,
    read_func_first_line,
    read_marco,
)
from ..gdbTools import execute_gdb_command
from typing import Annotated
import os
import json
from ..tool_timeout import timed_tool


def get_from_vmlinux(target: str, kind: str) -> dict | None:
    """
    Search for definition in vmlinux using GDB (via execute_gdb_command).
    Returns dict with keys: found, path, line, definition(content)
    """
    helper_path = os.path.join(os.path.dirname(__file__), "gdb_helper.py")

    try:
        # Set environment variables in GDB for the helper script
        use_ptype = "1" if kind == "struct" else "0"

        setup_cmd = (
            f"python import os; "
            f"os.environ['GDB_QUERY_TARGET'] = '{target}'; "
            f"os.environ['GDB_QUERY_KIND'] = '{kind}'; "
            f"os.environ['GDB_USE_PTYPE'] = '{use_ptype}'"
        )

        # Access the underlying function if wrapped by @tool
        exec_func = execute_gdb_command
        if hasattr(execute_gdb_command, "func"):
            exec_func = execute_gdb_command.func

        # Execute setup
        res = exec_func(setup_cmd)
        # We don't strictly check setup result as long as source works,
        # but if setup fails, source might run with wrong env.

        # Execute source
        res = exec_func(f"source {helper_path}")

        if isinstance(res, dict) and res.get("result") == "success":
            output_lines = res.get("output", [])
            for line in output_lines:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                        if data.get("found"):
                            return data
                    except:
                        continue
    except Exception:
        pass
    return None


@timed_tool(timeout_seconds=45)
def get_func_callback(
    func_names: Annotated[list[str], "List of function names to query"],
) -> Annotated[str, "Function definitions"]:
    """
    Retrieve the source code definitions for a list of functions.

    This tool searches the codebase for the definitions of the specified functions
    and returns their source code. It handles multiple definitions by prioritizing
    C source files over headers and using heuristics to find the actual implementation.
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


@timed_tool(timeout_seconds=45)
def get_caller_callback(
    func_names: Annotated[list[str], "List of function names to query for callers"],
) -> Annotated[str, "Call sites of the functions"]:
    """
    Retrieve the call sites (callers) for a list of functions.
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


@timed_tool(timeout_seconds=45)
def get_callee_callback(
    func_names: Annotated[list[str], "List of function names to query for callees"],
) -> Annotated[str, "Functions called by the specified functions"]:
    """
    Retrieve the functions called by the specified functions (callees).
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


@timed_tool(timeout_seconds=45)
def get_struct_callback(
    struct_names: Annotated[
        list[str], "List of struct names to query(e.g., ['task_struct', 'file'])"
    ],
) -> Annotated[str, "Struct definitions"]:
    """
    Retrieve the source code definitions for a list of structures.

    This tool searches the codebase for the definitions of the specified C structures
    and returns their source code.
    """
    response = ""
    for struct_name in struct_names:
        if struct_name.startswith("struct "):
            query_name = struct_name
            struct_name = struct_name[7:]  # keep clean name for display
        else:
            query_name = "struct " + struct_name

        # First try GDB/vmlinux for the most accurate definition (using ptype)
        gdb_res = get_from_vmlinux(query_name, "struct")
        if gdb_res and gdb_res.get("found"):
            if gdb_res.get("definition"):
                # Ptype approach succeeded
                response += (
                    f"Struct {struct_name} (from GDB ptype):\n```c\n{gdb_res['definition']}\n```\n"
                )
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


@timed_tool(timeout_seconds=45)
def get_global_var(
    var_names: Annotated[list[str], "List of global variable or macro names to query"],
) -> Annotated[str, "Global variable/macro definitions"]:
    """
    Retrieve the definitions of global variables or macros.

    This tool searches for global variables or preprocessor macros in the codebase.
    It automatically detects macros based on uppercase naming convention.
    """
    response = ""
    for var_name in var_names:
        if not var_name:
            response += "Error: empty variable name.\n"
            continue

        if var_name.isupper():
            var_def_loc = get_global_var_def_codequery(get_proj_path(), var_name, is_macro=True)
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
        if var_name.isupper():
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
        result = get_global_var.func(["init_cred"])
        if "not found" in result:
            print(f"⚠️ jiffies not found: {result}")
        else:
            print("jiffies definition found.")
            print(f"Snippet: {result[:200]}...")
    except Exception as e:
        print(f"❌ Exception in get_global_var: {e}")

    # 5. Test get_caller_callback
    print("\n[Test] get_caller_callback: vfs_read")
    try:
        result = get_caller_callback.func(["vfs_read"])
        if "No callers found" in result:
            print(f"⚠️ callers for vfs_read not found: {result}")
        else:
            print("Callers of vfs_read found.")
            print(f"Snippet: {result[:200]}...")
    except Exception as e:
        print(f"❌ Exception in get_caller_callback: {e}")

    # 6. Test get_callee_callback
    print("\n[Test] get_callee_callback: vfs_read")
    try:
        result = get_callee_callback.func(["vfs_read"])
        if "No callees found" in result:
            print(f"⚠️ callees for vfs_read not found: {result}")
        else:
            print("Callees of vfs_read found.")
            print(f"Snippet: {result[:200]}...")
    except Exception as e:
        print(f"❌ Exception in get_callee_callback: {e}")

    print("\nCodeQuery tests completed.")
