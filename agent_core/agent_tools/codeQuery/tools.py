from .codequery import proj_path
from langchain_core.tools import tool
from .codequery import get_func_def_codequery, get_struct_def_codequery, get_global_var_def_codequery, get_caller_codequery, get_callee_codequery
from .get_func_def import read_func, read_struct_def, read_global_var, read_func_first_line, read_marco
from typing import Annotated

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
        func_loc = get_func_def_codequery(proj_path, func_name)
        
        # heuristics: the definition of a function must NOT start with "\t"
        if func_loc and len(func_loc) > 0:
            func_loc_tmp = []
            for loc in func_loc:
                file_path, line_no = loc
                func_first_line = read_func_first_line(file_path, int(line_no), proj_path)
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
        file_path, line_no = func_loc[-1]

        # read the source code
        func_def = read_func(file_path, 0, proj_path, real_lineno=int(line_no))
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
        callers = get_caller_codequery(proj_path, func_name)
        if not callers or len(callers) == 0:
            response += f"No callers found for {func_name}.\n"
            continue
            
        response += f"Callers of {func_name}:\n"
        # Limit to top 20 to avoid context overflow
        for loc in callers[:20]:
            file_path, line_no = loc
            # Try to read the code line
            try:
                code_line = read_func_first_line(file_path, int(line_no), proj_path)
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
        callees = get_callee_codequery(proj_path, func_name)
        if not callees or len(callees) == 0:
            response += f"No callees found for {func_name}.\n"
            continue
            
        response += f"Functions called by {func_name}:\n"
        # Limit to top 20
        for loc in callees[:20]:
            file_path, line_no = loc
            try:
                code_line = read_func_first_line(file_path, int(line_no), proj_path)
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
            struct_name = struct_name[7:]
        struct_def = get_struct_def_codequery(proj_path, struct_name)
        if not struct_def or len(struct_def) == 0:
            response += f"Struct {struct_name} is not found.\n"
            continue

        # and let's use the last one
        file_path, line_no = struct_def[-1]

        # read the source code
        # struct_def = read_func(file_path, 0, proj_path, real_lineno=int(line_no))
        struct_def = read_struct_def(file_path, int(line_no), proj_path)
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
            var_def_loc = get_global_var_def_codequery(proj_path, var_name, is_marco=True)
            if var_def_loc:
                # and let's use the last one
                file_path, line_no = var_def_loc[-1]

                # read the source code
                var_def = read_marco(file_path, int(line_no), proj_path)
                response += f"{var_name} is defined as: \n```c\n{var_def}\n```\n"
                continue
        var_def_loc = get_global_var_def_codequery(proj_path, var_name) 
        if not var_def_loc:
            response += f"{var_name} is not found.\n"
            continue
            

        # and let's use the last one
        file_path, line_no = var_def_loc[-1]

        # read the source code
        if _is_macro_def(var_name):
            var_def = read_marco(file_path, int(line_no), proj_path)
        else:
            var_def = read_global_var(file_path, int(line_no), proj_path)
        response += f"Global variable {var_name} is defined as: \n```c\n{var_def}\n```\n"
    return response