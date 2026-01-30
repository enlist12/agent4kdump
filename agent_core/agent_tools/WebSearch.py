from langchain_core.tools import tool
from typing import Annotated
import requests
from bs4 import BeautifulSoup
from langchain_community.tools.tavily_search import TavilySearchResults
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Add proxy support in future

@tool
def web_search(
    query: Annotated[str, "The search query (e.g., 'Linux kernel use-after-free CVE-2023-1234')"],
    max_results: Annotated[int, "Maximum number of results to return"] = 5
) -> Annotated[str, "Search results from the web"]:
    """
    Search the web for information related to kernel bugs, CVEs, patches, and technical documentation using Tavily.
    
    This tool uses Tavily Search API (requires TAVILY_API_KEY env var) to search the web and returns relevant results.
    Useful for finding:
    - Linux kernel patches and commits
    - CVE details and security advisories
    - Bug reports and discussions
    - Technical documentation
    """
    try:
        # Check for API key
        if "TAVILY_API_KEY" not in os.environ:
             return "Error: TAVILY_API_KEY environment variable not set. Please set it in agent_core/.env"

        tavily = TavilySearchResults(max_results=max_results)
        
        # Execute search
        # Tavily tool expects {"query": "..."} input
        results = tavily.invoke({"query": query})
        
        if not results:
            return f"No search results found for: {query}"
        
        # Format output
        output = f"Search results for '{query}':\n\n"
        for i, result in enumerate(results, 1):
            # Tavily returns 'url' and 'content' usually
            url = result.get('url', 'No URL')
            content = result.get('content', '')
            # Sometimes title is not returned by default Tavily wrapper, but content is the snippet
            
            output += f"{i}. URL: {url}\n"
            if content:
                output += f"   Snippet: {content}\n"
            output += "\n"
        
        return output
        
    except Exception as e:
        return f"Error: Failed to perform Tavily search: {str(e)}"


@tool
def fetch_webpage_content(
    url: Annotated[str, "The URL of the webpage to fetch"],
    max_length: Annotated[int, "Maximum character length of content to return"] = 5000
) -> Annotated[str, "Content extracted from the webpage"]:
    """
    Fetch and extract the main text content from a webpage.
    
    Useful for reading:
    - Git commit details from kernel.org or GitHub
    - CVE descriptions from NVD or Mitre
    - Documentation pages
    - Bug tracker entries
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "header", "footer"]):
            script.decompose()
        
        # Get text
        text = soup.get_text(separator='\n', strip=True)
        
        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        content = '\n'.join(lines)
        
        # Truncate if too long
        if len(content) > max_length:
            content = content[:max_length] + "\n\n[Content truncated...]"
        
        return f"Content from {url}:\n\n{content}"
        
    except requests.Timeout:
        return f"Error: Request timed out for {url}"
    except requests.RequestException as e:
        return f"Error: Failed to fetch webpage: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"
    
def test_web_search():
    """
    Test suite for WebSearch functions.
    """
    print("Starting WebSearch tests...")
    
    # 1. Test web_search
    print("\n[Test] web_search")
    query = "Linux kernel CVE-2024-0001"
    print(f"Searching for: {query}")
    try:
        results = web_search.func(query, max_results=3)
        if "Error" in results:
            print(f"⚠️ Search failed: {results}")
        else:
            print("Search successful.")
            print(f"Results snippet:\n{results[:200]}...")
    except Exception as e:
        print(f"❌ Exception in web_search: {e}")

    # 2. Test fetch_webpage_content
    print("\n[Test] fetch_webpage_content")
    # Use a reliable URL, e.g., example.com or kernel.org
    url = "https://www.kernel.org"
    print(f"Fetching: {url}")
    try:
        content = fetch_webpage_content.func(url, max_length=500)
        if "Error" in content:
            print(f"⚠️ Fetch failed: {content}")
        else:
            print("Fetch successful.")
            print(f"Content snippet:\n{content[:200]}...")
    except Exception as e:
        print(f"❌ Exception in fetch_webpage_content: {e}")
        
    print("\nWebSearch tests completed.")