
import sys
import os

# Ensure root is in path so we can import agent_core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def main():
    print("Running all tool tests from project root...\n" + "="*50)

    # 1. File Tools
    try:
        from agent_core.agent_tools.fileTools import test_file_tools
        test_file_tools()
        print("="*50)
    except Exception as e:
        print(f"❌ fileTools tests failed: {e}")
        # import traceback
        # traceback.print_exc()

    # 2. Command Tools
    try:
        from agent_core.agent_tools.commandTools import test_command_tools
        test_command_tools()
        print("="*50)
    except Exception as e:
        print(f"❌ commandTools tests failed: {e}")

    # 3. Web Search Tools
    try:
        from agent_core.agent_tools.WebSearch import test_web_search
        test_web_search()
        print("="*50)
    except Exception as e:
        print(f"❌ WebSearch tests failed: {e}")

    # 4. Code Query Tools
    try:
        from agent_core.agent_tools.codeQuery.tools import test_code_query_tools
        test_code_query_tools()
        print("="*50)
    except Exception as e:
        print(f"❌ CodeQuery tests failed: {e}")

    print("\nAll tests execution finished.")

if __name__ == "__main__":
    main()
