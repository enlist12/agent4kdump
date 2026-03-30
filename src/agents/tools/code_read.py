from langchain.tools import tool


@tool
def read_file(filename: str) -> str:
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {filename}: {e}"


@tool
def read_file_by_linenum(filename: str, line: int, num_lines: int = 10) -> str:
    if line < 1:
        return f"Invalid line number: {line}"
    if num_lines < 1:
        return f"Invalid num_lines: {num_lines}"

    try:
        with open(filename, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if line > len(lines):
            return f"Line {line} exceeds file length ({len(lines)})"

        start = line - 1
        end = min(start + num_lines, len(lines))
        return "".join(f"{i + 1}: {lines[i]}" for i in range(start, end))
    except Exception as e:
        return f"Error reading {filename}: {e}"