import os
import re
from typing import Any, Dict, List

from agent_core.tools.WebSearch import fetch_webpage_content, web_search


URL_RE = re.compile(r"https?://[^\s)]+")


class LinuxBackgroundCollector:
    """Collect Linux kernel subsystem background independently from history retrieval."""

    def __init__(self, logger: Any) -> None:
        self.logger = logger

    def collect(self, profile: Dict[str, Any]) -> List[Dict[str, str]]:
        if "TAVILY_API_KEY" not in os.environ:
            return []

        queries = self._build_queries(profile)
        if not queries:
            return []

        backgrounds: List[Dict[str, str]] = []
        for query in queries[:2]:
            try:
                result_text = web_search.func(
                    query=query,
                    max_results=3,
                    search_depth="advanced",
                    include_domains=[
                        "docs.kernel.org",
                        "lore.kernel.org",
                        "kernel.org",
                        "syzkaller.appspot.com",
                    ],
                )
            except Exception as exc:
                self.logger.warning("web_search failed: %s", exc)
                continue

            if not isinstance(result_text, str) or result_text.startswith("Error:"):
                continue

            urls = URL_RE.findall(result_text)
            for url in urls[:2]:
                try:
                    page = fetch_webpage_content.func(url=url, max_length=2200)
                except Exception:
                    continue
                if not isinstance(page, str) or page.startswith("Error:"):
                    continue
                backgrounds.append(
                    {
                        "query": query,
                        "url": url,
                        "content": self._shorten(page, limit=1600),
                    }
                )
                if len(backgrounds) >= 3:
                    return backgrounds

        return backgrounds

    def _build_queries(self, profile: Dict[str, Any]) -> List[str]:
        kernel_version = profile.get("kernel_version", "unknown")
        drivers = profile.get("driver_candidates", [])
        functions = profile.get("functions", [])

        queries: List[str] = []
        if drivers:
            queries.append(f"Linux kernel {drivers[0]} driver architecture and data path")
            queries.append(f"docs.kernel.org {drivers[0]} driver design")
        if functions:
            queries.append(f"Linux kernel function {functions[0]} responsibilities and call chain")
        if kernel_version != "unknown":
            queries.append(f"Linux kernel {kernel_version} subsystem documentation and behavior changes")
        queries.append("Linux kernel driver debugging workflow docs.kernel.org")

        return list(dict.fromkeys(queries))

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[:limit] + " ..."
