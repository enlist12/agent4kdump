import os
import re
from diskcache import Cache

FORBIDDEN_KEYWORDS_PATTERN = re.compile(r'\b(if|while|for|else|switch|do)\b')


__location__ = os.path.realpath(
    os.path.join(os.getcwd(), os.path.dirname(__file__)))

cache_dir = "cache"
# _special_cases = json.load(
#     open(__location__ + os.sep + "special_cases.json", 'r'))


unsupported_msg = """
I am sorry, but currently I do not support this case, please answer "NOT SUPPORTED" directly
"""

def __is_line_end(line):
    if line.endswith(',\n'):
        return False
    return line.endswith(';\n') or line.endswith('}\n') or line.endswith(')\n') or line.endswith(')\n') or line.endswith('}\n') or line.endswith('{\n')

def __is_line_continue(line):
    return line.endswith(',\n') or line.endswith('"\n')

def __is_func_start_v2(line: str) -> bool:
    """
    Returns True if the given line likely starts a function definition
    based on our three rules.
    """
    # Rule 1: Must end with '{' after trimming trailing whitespace
    if not line.rstrip().endswith('{'):
        return False
    
    # Rule 2: Must not start with a space or a tab
    if not line:  # empty line check
        return False
    if line[0] in (' ', '\t'):
        return False
    
    # Rule 3: Cannot contain forbidden keywords as standalone words
    # (i.e., cannot match \bif\b, \bwhile\b, etc.)
    if FORBIDDEN_KEYWORDS_PATTERN.search(line):
        return False
    
    return True
    
def is_comment_line(line: str) -> bool:
    """
    Check if this line *appears* to be entirely a comment.
    For simplicity:
      - Single-line comment starting with //  OR
      - Entire line enclosed in /* ... */ with optional whitespace around.
    """
    stripped = line.strip()
    # Check for // comment
    if stripped.startswith('//'):
        return True
    
    # Check for /* comment */
    if stripped.startswith('/*') or stripped.endswith('*/'):
        return True
    
    if line.startswith('*'):
        return True
    
    return False

def __is_func_start_v3(line: str) -> bool:
    """
    (static) struct/int table_device *find_table_device(struct list_head *l, dev_t dev,
    """
    
    if not line.strip():
        return False
    
    if line[0] in (' ', '\t', '{'):
        return False
    
    if line.endswith(':'):
        return False
    
    if is_comment_line(line):
        return False
    
    return True
    
def __is_func_end(line):
    return line == '}'

def read_line(file_path: str, line_no, proj_path):
    return read_line_with_previous_part(file_path, line_no, proj_path)
    # if file_path.startswith("source/"):
    #     file_path = file_path[7:]
    # with open(os.path.join(proj_path, file_path), 'r', errors='ignore') as f:
    #     lines = f.readlines()
    #     # return lines[line_no-1]
    #     # find the start of this line

    #     line_start = line_no - 1  # Update: not include previous lines

    #     line_end = line_no - 1
    #     while line_end < len(lines):
    #         if __is_line_end(lines[line_end]):
    #             break
    #         line_end += 1
    #     return ''.join(lines[line_start:line_end+1])
    
def get_number_of_tabs(line):
    """
    Get the number of tabs and blanks at the beginning of a line.
    
    Args:
        line (str): The input line to analyze
        
    Returns:
        tuple: (number of tabs, number of spaces)
    """
    tab_count = 0
    space_count = 0
    
    for char in line:
        if char == '\t':
            tab_count += 1
        elif char == ' ':
            space_count += 1
        else:
            break
            
    return tab_count, space_count
    
def read_line_with_previous_part(file_path: str, line_no, proj_path):
    if file_path.startswith("source/"):
        file_path = file_path[7:]
    with open(os.path.join(proj_path, file_path), 'r', errors='ignore') as f:
        lines = f.readlines()
        # return lines[line_no-1]
        # find the start of this line

        line_start = line_no - 1 
        cur_line = line_no - 1
        line_end = line_no - 1
        # heuristic: if the previous line has same number of "\t", the previous line to be a seperated line
        n_tabs, n_blks = get_number_of_tabs(lines[line_start])
        
        while cur_line > 0:
            prev_line = lines[cur_line - 1]
            prev_n_tabs, prev_n_blks = get_number_of_tabs(prev_line)
            
            if __is_line_end(prev_line):
                break
            
            if (not __is_line_continue(prev_line)) and (prev_n_tabs, prev_n_blks) > (n_tabs, n_blks): # if the previous line has more indentation
                break
            
            if (not __is_line_continue(prev_line)) and prev_n_tabs == n_tabs and prev_n_blks == n_blks:
                break
            cur_line -= 1
            n_tabs, n_blks = prev_n_tabs, prev_n_blks
        
        # line_end = line_no - 1
        while line_end < len(lines):
            if __is_line_end(lines[line_end]):
                break
            line_end += 1
        return ''.join(lines[cur_line:line_end+1])


def __is_func_start(line):
    return line == "{\n"

marco_pattern = re.compile(r'^(?!\t)\s*[A-Z0-9_]+\s*\(')
def __is_marco_expend(line):
    """
    Determines if a given line is an expanded macro based on the following rules:
    - Does not start with a tab character.
    - After any leading spaces, the first part of the line is composed of uppercase letters, numbers, and underscores.
    - Followed by an opening parenthesis '('.
    
    Args:
        line (str): A line of code.
        
    Returns:
        bool: True if the line matches the criteria for an expanded macro, False otherwise.
    """
    if line.startswith('//') or line.startswith('/*'):
        return False
    return bool(marco_pattern.match(line))

def read_marco(file_path: str, line_no, proj_path):
    # from the first line, read until line ends not with '\'
    with open(os.path.join(proj_path, file_path), 'r', errors='ignore') as f:
        lines = f.readlines()
        real_lineno = line_no - 1
        res = ""
        
        while real_lineno > 0:
            cur_line = lines[real_lineno]
            if not cur_line.endswith(",\n"):
                break
            real_lineno -= 1
        
        
        while real_lineno < len(lines):
            cur_line = lines[real_lineno]
            res += cur_line
            # if the line ends with '\' or ',', then it is a multi-line marco
            if not cur_line.endswith("\\\n") and not cur_line.endswith(",\n") and not cur_line.endswith("{\n"):
                break
            real_lineno += 1
        return res

def read_func(file_path: str, line_no, proj_path, real_lineno=None):
    if real_lineno is None:
        real_lineno = get_func_start_line(file_path, line_no, proj_path)
    if real_lineno is None:
        return unsupported_msg
    func_def, _ = __read_func(file_path, real_lineno, proj_path)
    return func_def

def read_func_first_line(file_path: str, line_no, proj_path):
    real_file_path = os.path.join(proj_path, file_path)
    with open(real_file_path, 'r', errors='ignore') as f:
        lines = f.readlines()
        return lines[line_no - 1]
    return None

def read_func_first_part(file_path: str, line_no, proj_path):
    func_start_line = get_func_start_line(file_path, line_no, proj_path)
    if func_start_line is None:
        return unsupported_msg
    
    func_def, comment_start = __read_func(
        file_path, func_start_line, proj_path)
    lines_diff = line_no - comment_start
    lines = func_def.split('\n')

    res = lines[:lines_diff]

    target_line_src = read_line(file_path, line_no, proj_path)

    return '\n'.join(res) + '\n' + target_line_src + '\n' + "..." + '\n}\n'


def read_func_second_part(file_path: str, line_no, proj_path):
    # reading from the @line_no to the end of the function
    func_start_line = get_func_start_line(file_path, line_no, proj_path)
    if func_start_line is None:
        return unsupported_msg
    
    func_def, comment_start = __read_func(
        file_path, func_start_line, proj_path)
    lines_diff = line_no - comment_start
    lines = func_def.split('\n')
    
    headers = ""
    for i in range(lines_diff):
        headers += lines[i] + '\n'
        if lines[i].endswith("{"): # end of the prototype
            break
    
    lines_diff -= 1
    while (lines[lines_diff].startswith("\t\t")): # if the line is not "the outermost" line
        lines_diff -= 1
    
    res = headers + '\n...\n' + '\n'.join(lines[lines_diff:])
    return res
    


def get_func_start_line(file_path: str, line_no, proj_path):
    with Cache(cache_dir+"/cache_func_read", size_limit=1 * 1024 ** 3) as cache:
        # Create a cache key using the function name and version, with size limit = 1GB
        cache_key = f"{proj_path}:{file_path}:{line_no}"

        # Check if the result is already in the cache
        if cache_key in cache:
            real_lineno = cache[cache_key]
            return real_lineno

        # find the start line of the function
        with open(os.path.join(proj_path, file_path), 'r', errors='ignore') as f:
            lines = f.readlines()
            if __is_marco_expend(lines[line_no - 1]):
                return None
            
            # find the start of this func
            line_start = line_no - 2
            while line_start >= 0:
                # if __is_func_start(lines[line_start]):
                # if __is_func_start_v2(lines[line_start]):
                if __is_func_start_v3(lines[line_start]):
                    break
                line_start -= 1

            # find the start of the prototype line
            # proto_start = line_start - 1
            # while proto_start >= 0:
            #     # if __is_line_end(lines[proto_start]):
            #     #     break
            #     if not lines[proto_start].startswith('\t'):
            #         break
            #     proto_start -= 1
            # # 1-based -> 1-based
            # proto_start += 1

            real_lineno = line_start + 1
            cache[cache_key] = real_lineno
            return real_lineno


def __read_func(file_path: str, line_number, proj_path):
    if file_path.startswith("source/"):
        file_path = file_path[7:]

    # version = proj_path.split(os.sep)[-1]

    with Cache(cache_dir+"/cache_func_helper", size_limit=1 * 1024 ** 3) as cache:
        # Create a cache key using the function name and version, with size limit = 1GB
        cache_key = f"{proj_path}:{file_path}:{line_number}"

        # Check if the result is already in the cache
        if cache_key in cache:
            func_def, comment_start = cache[cache_key]
            return func_def, comment_start
        
    with open(os.path.join(proj_path, file_path), 'r', errors='ignore') as f:
        lines = f.readlines()
        
        if __is_marco_expend(lines[line_number - 1]):
            return None, None
        
        symbol_line = lines[line_number - 1]

        # Find the starting line of the comments by searching for '*/' before the function definition
        comment_start = line_number - 1
        comments_found = False
        while line_number - 3 < comment_start or comments_found:
            if comment_start < 0:
                break
            
            if lines[comment_start - 1] == '\n':
                break
                
            if (not comments_found) and lines[comment_start - 1].strip().startswith('*'):
                comments_found = True

            if lines[comment_start - 1].strip().startswith('/*'):
                comments_found = True
                break
            comment_start -= 1

        # Combine comments (if any) and function definition
        if comments_found:
            function_definition = lines[comment_start - 1:line_number]
        else:
            function_definition = [lines[line_number - 1]]
            comment_start = line_number
            
        # if the start line is "#define", or CAPS, let's return up to the first "empty" line
        if symbol_line.startswith("#define") or symbol_line[0].isupper():
            i = line_number
            while i < len(lines):
                line = lines[i]
                function_definition.append(line)
                if line.strip() == '':
                    break
                i += 1

            res_def = ''.join(function_definition)
            cache[cache_key] = res_def, comment_start
            return res_def, comment_start

        # Include the implementation code up to the closing brace of the function
        i = line_number
        while i < len(lines):
            line = lines[i]
            function_definition.append(line)
            if line.startswith('}'):
                break
            i += 1

        res_def = ''.join(function_definition)
        cache[cache_key] = res_def, comment_start
        return res_def, comment_start


def read_struct_def(file_path: str, line_no, proj_path):
    with Cache(cache_dir+"/cache_struct_read", size_limit=1 * 1024 ** 3) as cache:
        # Create a cache key using the function name and version, with size limit = 1GB
        cache_key = f"{proj_path}:{file_path}:{line_no}"

        # Check if the result is already in the cache
        if cache_key in cache:
            real_lineno = cache[cache_key]
            return real_lineno

        # find the start line of the struct
        with open(os.path.join(proj_path, file_path), 'r', errors='ignore') as f:
            lines = f.readlines()
            real_lineno = line_no - 1;
            if __is_marco_expend(lines[real_lineno]):
                return None

            res = ""
            
            while real_lineno < len(lines):
                # res += lines[real_lineno]
                cur_line = lines[real_lineno]
                res += cur_line
                if cur_line.endswith(";\n") and cur_line.startswith("}"):
                    break
                real_lineno += 1
            
            return res
        
def read_global_var(file_path, line_no, proj_path):
    with Cache(cache_dir+"/cache_global_var_read", size_limit=1 * 1024 ** 3) as cache:
        # Create a cache key using the function name and version, with size limit = 1GB
        cache_key = f"{proj_path}:{file_path}:{line_no}"

        # Check if the result is already in the cache
        if cache_key in cache:
            real_lineno = cache[cache_key]
            return real_lineno

        # find the start line of the struct
        with open(os.path.join(proj_path, file_path), 'r', errors='ignore') as f:
            lines = f.readlines()
            real_lineno = line_no - 1;
            if __is_marco_expend(lines[real_lineno]):
                return None

            res = ""
            
            while real_lineno < len(lines):
                # res += lines[real_lineno]
                cur_line = lines[real_lineno]
                res += cur_line
                if cur_line.endswith(";\n"):
                    break
                real_lineno += 1
            
            return res