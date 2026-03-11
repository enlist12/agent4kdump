import os
import sys
import subprocess
import logging
from diskcache import Cache
from contextlib import contextmanager
import time

cache_dir = "cache"
proj_path = None

def set_proj_path(path):
    global proj_path
    proj_path = path

def get_proj_path():
    global proj_path
    if proj_path is None:
        raise ValueError("Project path is not set. Call set_proj_path first.")
    return proj_path

@contextmanager
def log_time(desc):
    logging.info(f"Starting {desc}")
    start_time = time.perf_counter()
    yield
    end_time = time.perf_counter()
    logging.info(f"{desc} took {end_time - start_time} seconds")


def __get_db_file(project_root_path):
    return os.path.join(project_root_path, 'cq.db')


def __exist_db_file(project_root_path):
    return os.path.exists(__get_db_file(project_root_path))


def __has_dependency():
    # Check if the codequery command is available
    try:
        subprocess.run(['cscope', '--version'],
                       capture_output=True, check=True)
        subprocess.run(['ctags', '--version'],
                       capture_output=True, check=True)
        subprocess.run(['cqmakedb', '-v'], capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


__HAS_DEPENDENCY = __has_dependency()


def create_cq_db(project_path):
    try:
        # find all source files (*.c, *.cpp, *.h, *.hpp) in the project directory
        # and write to "cscope.files"
        # with log_time("find source files"):
        cscope_files_path = os.path.join(project_path, 'cscope.files')
        
        if os.path.exists(cscope_files_path):
            return
        
        with open(cscope_files_path, 'w') as f:
            subprocess.run(
                ['find', '.', '-type', 'f', '(', '-name', '*.c', '-o', '-name',
                 '*.cpp', '-o', '-name', '*.h', '-o', '-name', '*.hpp', ')'],
                cwd=project_path,
                stdout=f,
                stderr=sys.stderr, check=True)

        with log_time("cscope database creation"):
            subprocess.run(['cscope', '-b', '-c', '-k'],
                           cwd=project_path, check=True)

        with log_time("ctags database creation"):
            subprocess.run(['ctags', '--fields=+i', '-n', '-L', './cscope.files'],
                           cwd=project_path, check=True)

        with log_time("codequery database creation"):
            subprocess.run(['cqmakedb', '-s', './cq.db', '-c' './cscope.out', '-t', './tags', '-p'],
                           cwd=project_path, check=True)

    except subprocess.CalledProcessError:
        raise Exception("Error creating codequery database")


def __get_func_cq(project_path, function_name):
    # def find_function_location(function_name, cqsearch_db, project_path):
    # Construct the cqsearch command
    cqsearch_db = __get_db_file(project_path)

    if not __exist_db_file(project_path):
        # print(f"Error: No .db file found in {project_path}", file=sys.stderr)
        if not __HAS_DEPENDENCY:
            logging.error(
                "Error: Missing cscope, ctags, or codequery. Please install them first.")
            # print("Error: Missing cscope, ctags, or codequery. Please install them first.", file=sys.stderr)
            return None

        logging.info("Creating codequery database")
        create_cq_db(project_path)

    command = [
        'cqsearch',
        '-s', cqsearch_db,
        '-p', '2',
        '-u',
        '-e',
        '-t', function_name
    ]
    res = []

    # Run the cqsearch command and capture its output
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error executing cqsearch: {e}")
        return res

    # Extract the relevant file path from the output
    output_lines = result.stdout.splitlines()

    for line in output_lines:
        line = line.split('\t')[1]
        if '$HOME' in line:
            # Extract the path after the project base dir
            base_dir_pattern = os.path.basename(project_path)
            start_index = line.rfind(base_dir_pattern)
            if start_index != -1:
                # Adjust to get the path relative to the project's base directory
                # relative_path = line[start_index + len(base_dir_pattern) + 1:].split(':')[0]
                # return line[start_index + len(base_dir_pattern) + 1:].split(':')
                res.append(
                    line[start_index + len(base_dir_pattern) + 1:].split(':'))
        else:
            base_dir_pattern = os.path.basename(project_path)
            relative_path_start_index = line.rfind(
                base_dir_pattern) + len(base_dir_pattern)+1
            relative_path = line[relative_path_start_index:].split(':')
            # return relative_path
            res.append(relative_path)

    return res


def __get_struct_cq(project_path, struct_name):
    # def find_function_location(function_name, cqsearch_db, project_path):
    # Construct the cqsearch command
    cqsearch_db = __get_db_file(project_path)

    if not __exist_db_file(project_path):
        # print(f"Error: No .db file found in {project_path}", file=sys.stderr)
        if not __HAS_DEPENDENCY:
            logging.error(
                "Error: Missing cscope, ctags, or codequery. Please install them first.")
            # print("Error: Missing cscope, ctags, or codequery. Please install them first.", file=sys.stderr)
            return None

        logging.info("Creating codequery database")
        create_cq_db(project_path)

    command = [
        'cqsearch',
        '-s', cqsearch_db,
        '-p', '3',
        '-u',
        '-e',
        '-t', struct_name
    ]
    res = []

    # Run the cqsearch command and capture its output
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error executing cqsearch: {e}")
        return res

    # Extract the relevant file path from the output
    output_lines = result.stdout.splitlines()

    for line in output_lines:
        line = line.split('\t')[1]
        if '$HOME' in line:
            # Extract the path after the project base dir
            base_dir_pattern = os.path.basename(project_path)
            start_index = line.rfind(base_dir_pattern)
            if start_index != -1:
                # Adjust to get the path relative to the project's base directory
                # relative_path = line[start_index + len(base_dir_pattern) + 1:].split(':')[0]
                # return line[start_index + len(base_dir_pattern) + 1:].split(':')
                res.append(
                    line[start_index + len(base_dir_pattern) + 1:].split(':'))
        else:
            base_dir_pattern = os.path.basename(project_path)
            relative_path_start_index = line.rfind(
                base_dir_pattern) + len(base_dir_pattern)+1
            relative_path = line[relative_path_start_index:].split(':')
            # return relative_path
            res.append(relative_path)

    return res


def __get_union_cq(project_path, union_name):
    # some "struct" are actually "union", but we can't find from `__get_struct_cq`
    # find symbole and `grep -e 'union.*{'`
    
    cq_db = __get_db_file(project_path)
    command = [
        'cqsearch',
        '-s', cq_db,
        '-p', '1',
        '-u',
        '-e',
        '-t', union_name
    ]
    
    res = []
    cqsearch_result = subprocess.run(command, capture_output=True, text=True)
    if cqsearch_result.returncode != 0:
        logging.error("Error running cqsearch command.")
        return None
    
    result = subprocess.run(
        ['grep', '-e', 'union.*{'], input=cqsearch_result.stdout, capture_output=True, text=True)
    if result.returncode not in [0, 1]:
        logging.error("Error filtering cqsearch results with grep.")
        return None
    
    output_lines = result.stdout.splitlines()
    for line in output_lines:
        line = line.split('\t')[1]
        
        if '$HOME' in line:
            base_dir_pattern = os.path.basename(project_path)
            start_index = line.rfind(base_dir_pattern)
            if start_index != -1:
                res.append(
                    line[start_index + len(base_dir_pattern) + 1:].split(':'))
        else:
            base_dir_pattern = os.path.basename(project_path)
            relative_path_start_index = line.rfind(
                base_dir_pattern) + len(base_dir_pattern)+1
            relative_path = line[relative_path_start_index:].split(':')
            res.append(relative_path)
            
    return res
    


def __get_global_var_cq(project_path, var_name, grep_pattern='struct'):
    # def find_function_location(function_name, cqsearch_db, project_path):
    # Construct the cqsearch command
    cqsearch_db = __get_db_file(project_path)

    if not __exist_db_file(project_path):
        # print(f"Error: No .db file found in {project_path}", file=sys.stderr)
        if not __HAS_DEPENDENCY:
            logging.error(
                "Error: Missing cscope, ctags, or codequery. Please install them first.")
            # print("Error: Missing cscope, ctags, or codequery. Please install them first.", file=sys.stderr)
            return None

        logging.info("Creating codequery database")
        create_cq_db(project_path)

    command = [
        'cqsearch',
        '-s', cqsearch_db,
        '-p', '1',
        '-u',
        '-e',
        '-t', var_name
    ]
    res = []

    # rune cqsearch and "grep 'struct'" with pipe
    # heuristics: most global variables are an instance of a struct (or array of struct)
    # EXAMPLE: `cqsearch -s cq.db -p 1 -u -e -t "slim_rx_cfg"

    # run cqsearch
    cqsearch_result = subprocess.run(command, capture_output=True, text=True)
    if cqsearch_result.returncode != 0:
        logging.error("Error running cqsearch command.")
        return None

    # pipe the output of cqsearch to grep pattern
    result = subprocess.run(
        ['grep', grep_pattern], input=cqsearch_result.stdout, capture_output=True, text=True)
    # grep returns 1 if no matches are found
    if result.returncode not in [0, 1]:
        logging.error("Error filtering cqsearch results with grep.")
        return None

    # Extract the relevant file path from the output
    output_lines = result.stdout.splitlines()

    for line in output_lines:
        line = line.split('\t')[1]
        if '$HOME' in line:
            # Extract the path after the project base dir
            base_dir_pattern = os.path.basename(project_path)
            start_index = line.rfind(base_dir_pattern)
            if start_index != -1:
                # Adjust to get the path relative to the project's base directory
                # relative_path = line[start_index + len(base_dir_pattern) + 1:].split(':')[0]
                # return line[start_index + len(base_dir_pattern) + 1:].split(':')
                res.append(
                    line[start_index + len(base_dir_pattern) + 1:].split(':'))
        else:
            base_dir_pattern = os.path.basename(project_path)
            relative_path_start_index = line.rfind(
                base_dir_pattern) + len(base_dir_pattern)+1
            relative_path = line[relative_path_start_index:].split(':')
            # return relative_path
            res.append(relative_path)

    return res


def get_func_def_codequery(proj, req_func):
    with Cache(cache_dir+"/cache_cq", size_limit=1 * 1024 ** 3) as cache:
        # Create a cache key using the function name and version, with size limit = 1GB
        cache_key = f"{proj}:{req_func}"
        if cache_key not in cache:
            res = __get_func_cq(proj, req_func)
            if res is None or len(res) == 0:
                return None
            cache[cache_key] = res
        return cache[cache_key]


def get_struct_def_codequery(proj, req_struct):
    with Cache(cache_dir+"/cache_cq_struct", size_limit=1 * 1024 ** 3) as cache:
        # Create a cache key using the function name and version, with size limit = 1GB
        cache_key = f"{proj}:{req_struct}"
        if cache_key not in cache:
            res = __get_struct_cq(proj, req_struct)
            if res is None or len(res) == 0:
                # try to find union
                res = __get_union_cq(proj, req_struct)
                if len(res) == 0 or res is None:
                    return None
            cache[cache_key] = res
        return cache[cache_key]
    

def get_global_var_def_codequery(proj, req_var, is_macro=False):
    with Cache(cache_dir+"/cache_cq_var", size_limit=1 * 1024 ** 3) as cache:
        # Create a cache key using the function name and version, with size limit = 1GB
        cache_key = f"{proj}:{req_var}"
        if cache_key not in cache:
            if is_macro:
                res = __get_global_var_cq(proj, req_var, 'define '+req_var)
                if res is None or len(res) == 0:
                    # considering "enum" as well
                    res = __get_global_var_cq(proj, req_var, req_var + ',')
                    if res is None or len(res) == 0:
                        return None
            else:
                res = __get_global_var_cq(proj, req_var)
                if res is None or len(res) == 0:
                    res = __get_global_var_cq(proj, req_var, 'static')
                    if res is None or len(res) == 0:
                        return None
            cache[cache_key] = res
        return cache[cache_key]


def __get_caller_cq(project_path, function_name):
    # Construct the cqsearch command
    cqsearch_db = __get_db_file(project_path)

    if not __exist_db_file(project_path):
        if not __HAS_DEPENDENCY:
            logging.error(
                "Error: Missing cscope, ctags, or codequery. Please install them first.")
            return None

        logging.info("Creating codequery database")
        create_cq_db(project_path)

    command = [
        'cqsearch',
        '-s', cqsearch_db,
        '-p', '6',  # 6: Functions calling this function
        '-u',
        '-e',
        '-t', function_name
    ]
    res = []

    # Run the cqsearch command and capture its output
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error executing cqsearch: {e}")
        return res

    # Extract the relevant file path from the output
    output_lines = result.stdout.splitlines()

    for line in output_lines:
        line = line.split('\t')[1]
        if '$HOME' in line:
            # Extract the path after the project base dir
            base_dir_pattern = os.path.basename(project_path)
            start_index = line.rfind(base_dir_pattern)
            if start_index != -1:
                res.append(
                    line[start_index + len(base_dir_pattern) + 1:].split(':'))
        else:
            base_dir_pattern = os.path.basename(project_path)
            relative_path_start_index = line.rfind(
                base_dir_pattern) + len(base_dir_pattern)+1
            relative_path = line[relative_path_start_index:].split(':')
            res.append(relative_path)

    return res


def __get_callee_cq(project_path, function_name):
    # Construct the cqsearch command
    cqsearch_db = __get_db_file(project_path)

    if not __exist_db_file(project_path):
        if not __HAS_DEPENDENCY:
            logging.error(
                "Error: Missing cscope, ctags, or codequery. Please install them first.")
            return None

        logging.info("Creating codequery database")
        create_cq_db(project_path)

    command = [
        'cqsearch',
        '-s', cqsearch_db,
        '-p', '7',  # 7: Functions called by this function
        '-u',
        '-e',
        '-t', function_name
    ]
    res = []

    # Run the cqsearch command and capture its output
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error executing cqsearch: {e}")
        return res

    # Extract the relevant file path from the output
    output_lines = result.stdout.splitlines()

    for line in output_lines:
        line = line.split('\t')[1]
        if '$HOME' in line:
            # Extract the path after the project base dir
            base_dir_pattern = os.path.basename(project_path)
            start_index = line.rfind(base_dir_pattern)
            if start_index != -1:
                res.append(
                    line[start_index + len(base_dir_pattern) + 1:].split(':'))
        else:
            base_dir_pattern = os.path.basename(project_path)
            relative_path_start_index = line.rfind(
                base_dir_pattern) + len(base_dir_pattern)+1
            relative_path = line[relative_path_start_index:].split(':')
            res.append(relative_path)

    return res


def get_caller_codequery(proj, req_func):
    with Cache(cache_dir+"/cache_cq_caller", size_limit=1 * 1024 ** 3) as cache:
        cache_key = f"{proj}:{req_func}"
        if cache_key not in cache:
            res = __get_caller_cq(proj, req_func)
            if res is None or len(res) == 0:
                return None
            cache[cache_key] = res
        return cache[cache_key]


def get_callee_codequery(proj, req_func):
    with Cache(cache_dir+"/cache_cq_callee", size_limit=1 * 1024 ** 3) as cache:
        cache_key = f"{proj}:{req_func}"
        if cache_key not in cache:
            res = __get_callee_cq(proj, req_func)
            if res is None or len(res) == 0:
                return None
            cache[cache_key] = res
        return cache[cache_key]
