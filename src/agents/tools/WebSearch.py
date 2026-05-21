from typing import Annotated
import os

import requests
from bs4 import BeautifulSoup
from dotenv import find_dotenv, load_dotenv
from langchain_tavily import TavilySearch
from .tool_timeout import timed_tool

load_dotenv(find_dotenv())


@timed_tool(timeout_seconds=30)
def web_search(
    query: Annotated[str, "The search query. Construct freely based on your analysis - no fixed format required."],
    max_results: Annotated[int, "Maximum number of results to return"] = 5,
    search_depth: Annotated[str, "Search depth: 'basic' (fast) or 'advanced' (deeper, recommended for technical queries)"] = "advanced",
    include_domains: Annotated[list[str], "List of domains to prioritize, e.g. ['syzkaller.appspot.com', 'nvd.nist.gov', 'lore.kernel.org']. Empty list means no restriction."] = [],
) -> Annotated[str, "Search results from the web"]:
    """
    Search the web for information related to kernel bugs, CVEs, patches, and technical documentation using Tavily.

    This tool uses Tavily Search API (requires TAVILY_API_KEY env var) to search the web and returns relevant results.
    Useful for finding:
    - Syzbot crash reports: use include_domains=['syzkaller.appspot.com']
    - CVE details: use include_domains=['nvd.nist.gov', 'cve.mitre.org']
    - Kernel patches/commits: use include_domains=['lore.kernel.org', 'git.kernel.org']
    - Use search_depth='advanced' for better results on technical queries
    """
    if "TAVILY_API_KEY" not in os.environ:
        return "Error: TAVILY_API_KEY environment variable not set. Please set it in .env"

    if max_results <= 0:
        return "Error: max_results must be greater than 0."

    tavily_kwargs = {
        "max_results": max_results,
        "search_depth": search_depth,
    }
    if include_domains:
        tavily_kwargs["include_domains"] = include_domains

    tavily = TavilySearch(**tavily_kwargs)
    response = tavily.invoke({"query": query})

    if isinstance(response, dict):
        results = response.get("results", []) or []
        answer = response.get("answer")
    elif isinstance(response, list):
        results = response
        answer = None
    else:
        results = []
        answer = None

    if not results:
        return f"No search results found for: {query}"

    output = f"Search results for '{query}':\n\n"
    if answer:
        output += f"Answer: {answer}\n\n"

    for i, result in enumerate(results, 1):
        title = result.get("title", "No title")
        url = result.get("url", "No URL")
        content = result.get("content", "")

        output += f"{i}. Title: {title}\n"
        output += f"   URL: {url}\n"
        if content:
            output += f"   Snippet: {content}\n"
        output += "\n"

    return output


@timed_tool(timeout_seconds=20)
def fetch_webpage_content(
    url: Annotated[str, "The URL of the webpage to fetch"],
    max_length: Annotated[int, "Maximum character length of content to return"] = 5000,
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

        soup = BeautifulSoup(response.text, "html.parser")

        for script in soup(["script", "style", "nav", "header", "footer"]):
            script.decompose()

        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        content = "\n".join(lines)

        if len(content) > max_length:
            content = content[:max_length] + "\n\n[Content truncated...]"

        return f"Content from {url}:\n\n{content}"
    except requests.Timeout:
        return f"Error: Request timed out for {url}"
    except requests.RequestException as e:
        return f"Error: Failed to fetch webpage: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


def test_web_search() -> None:
    """Simple smoke tests for web search tools."""
    print("Starting WebSearch tests...")

    print("\n[Test] web_search")
    if "TAVILY_API_KEY" in os.environ:
        query = "Linux kernel use-after-free CVE"
        print(f"Searching for: {query}")
        results = web_search.func(query, max_results=3)
        if results.startswith("Error:"):
            print(f"Search failed: {results}")
        else:
            print("Search successful.")
            print(f"Results snippet:\n{results[:300]}...")
    else:
        print("Skipped web_search test: TAVILY_API_KEY is not set.")

    print("\n[Test] fetch_webpage_content")
    url = "https://www.kernel.org"
    print(f"Fetching: {url}")
    content = fetch_webpage_content.func(url, max_length=500)
    if content.startswith("Error:"):
        print(f"Fetch failed: {content}")
    else:
        print("Fetch successful.")
        print(f"Content snippet:\n{content[:300]}...")

    print("\nWebSearch tests completed.")


if __name__ == "__main__":
    test_web_search()
