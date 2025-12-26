import re
from langchain_core.tools import tool
from .codequery import get_func_def_codequery, get_struct_def_codequery, get_global_var_def_codequery
from .get_func_def import read_func, read_struct_def, read_global_var, read_func_first_line, read_marco

@tool
def get_func_callback(task, args):
    proj_path = task['proj_dir']
    response = ""
    for func_name in args:
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


_current_caller_pos = {}

@tool
def get_caller_callback(task, args):
    pass

def clear_counter():
    _current_caller_pos.clear()

@tool
def get_struct_callback(task, args):
    proj_path = task['proj_dir']
    response = ""
    for struct_name in args:
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
def get_global_var(task, args):
    proj_path = task['proj_dir']
    response = ""
    for var_name in args:
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