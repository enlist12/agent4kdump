
import gdb
import json
import sys
import os

def check_symbol(symbol_name, kind, use_ptype=False):
    result = {
        "found": False,
        "name": symbol_name,
        "type": kind,
        "path": None,
        "line": None,
        "definition": None
    }
    
    try:
        if kind == "struct" and use_ptype:
            # Use ptype to get the definition text
            # This is reliable for types even if source location is missing
            try:
                output = gdb.execute(f"ptype {symbol_name}", to_string=True)
                if output and "type =" in output:
                    result["found"] = True
                    result["definition"] = output
                    return result
            except Exception as e:
                result["error"] = str(e)
                # Fallthrough to try symbol lookup if ptype fails (unlikely for valid type)

        # For structs, we need to look up the type or the tag
        if kind == "struct":
            # Remove "struct " prefix if present for lookup
            clean_name = symbol_name
            if clean_name.startswith("struct "):
                clean_name = clean_name[7:]
            
            # GDB Python API constants might vary
            domain = getattr(gdb, 'SYMBOL_STRUCT_DOMAIN', getattr(gdb, 'STRUCT_DOMAIN', 2))
            
            # Try lookup_global_symbol first (no block argument needed)
            if hasattr(gdb, 'lookup_global_symbol'):
                symbol = gdb.lookup_global_symbol(clean_name, domain)
            else:
                 symbol, _ = gdb.lookup_symbol(clean_name, None, domain)
        else:
            # Function lookup (VAR_DOMAIN/FUNCTION_DOMAIN is default)
            if hasattr(gdb, 'lookup_global_symbol'):
                symbol = gdb.lookup_global_symbol(symbol_name)
            else:
                symbol, _ = gdb.lookup_symbol(symbol_name)
            
        if symbol and symbol.symtab:
            result["found"] = True
            result["path"] = symbol.symtab.filename
            result["line"] = symbol.line
        
    except Exception as e:
        result["error"] = str(e)
    
    return result

def main():
    target = os.environ.get("GDB_QUERY_TARGET")
    kind = os.environ.get("GDB_QUERY_KIND", "func")
    use_ptype = os.environ.get("GDB_USE_PTYPE") == "1"
    
    if target:
        res = check_symbol(target, kind, use_ptype)
        print(json.dumps(res))

if __name__ == "__main__":
    main()
