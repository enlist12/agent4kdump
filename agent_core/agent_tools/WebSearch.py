from langchain_core.tools import tool
from typing import Annotated, Optional
import os
import requests
from bs4 import BeautifulSoup
import json

# Add proxy support in future

@tool
def web_search(
    query: str,
    max_results: int = 5
) -> Annotated[str, "Search results from the web"]:
    """
    Search the web for information related to kernel bugs, CVEs, patches, and technical documentation.
    
    This tool uses DuckDuckGo API (no API key required) to search the web and returns relevant results.
    Useful for finding:
    - Linux kernel patches and commits
    - CVE details and security advisories
    - Bug reports and discussions
    - Technical documentation
    
    Args:
        query (str): The search query (e.g., "Linux kernel use-after-free CVE-2023-1234")
        max_results (int): Maximum number of results to return (default: 5)
        
    Returns:
        str: Formatted search results with titles, URLs, and snippets
    """
    try:
        # Use DuckDuckGo HTML search (no API key needed)
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        
        # Parse search results
        for result in soup.find_all('div', class_='result')[:max_results]:
            title_elem = result.find('a', class_='result__a')
            snippet_elem = result.find('a', class_='result__snippet')
            
            if title_elem:
                title = title_elem.get_text(strip=True)
                link = title_elem.get('href', '')
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                
                results.append({
                    'title': title,
                    'url': link,
                    'snippet': snippet
                })
        
        if not results:
            return f"No search results found for: {query}"
        
        # Format output
        output = f"Search results for '{query}':\n\n"
        for i, result in enumerate(results, 1):
            output += f"{i}. {result['title']}\n"
            output += f"   URL: {result['url']}\n"
            if result['snippet']:
                output += f"   {result['snippet']}\n"
            output += "\n"
        
        return output
        
    except requests.Timeout:
        return "Error: Search request timed out"
    except requests.RequestException as e:
        return f"Error: Failed to perform web search: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def fetch_webpage_content(
    url: str,
    max_length: int = 5000
) -> Annotated[str, "Content extracted from the webpage"]:
    """
    Fetch and extract the main text content from a webpage.
    
    Useful for reading:
    - Git commit details from kernel.org or GitHub
    - CVE descriptions from NVD or Mitre
    - Documentation pages
    - Bug tracker entries
    
    Args:
        url (str): The URL of the webpage to fetch
        max_length (int): Maximum character length of content to return (default: 5000)
        
    Returns:
        str: The extracted text content from the webpage
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