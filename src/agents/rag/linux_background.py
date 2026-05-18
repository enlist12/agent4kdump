import os
import re
from typing import Any

URL_RE = re.compile(r"https?://[^\s)]+")


class LinuxBackgroundCollector:
    """Optionally collect a few Linux documentation snippets for the crash profile."""

    def __init__(self, logger: Any) -> None:
        self.logger = logger

    def collect(self, profile: dict[str, Any]) -> list[dict[str, str]]:
        if "TAVILY_API_KEY" not in os.environ:
            return []
        from agent_core.tools.WebSearch import fetch_webpage_content, web_search

        snippets: list[dict[str, str]] = []
        for query in self._queries(profile)[:2]:
            try:
                result_text = str(
                    web_search.func(
                        query=query,
                        max_results=3,
                        search_depth="advanced",
                        include_domains=["docs.kernel.org", "lore.kernel.org", "kernel.org", "syzkaller.appspot.com"],
                    )
                )
            except Exception as exc:
                self.logger.warning("web_search failed: %s", exc)
                continue
            if result_text.startswith("Error:"):
                continue
            for url in URL_RE.findall(result_text)[:2]:
                try:
                    page = str(fetch_webpage_content.func(url=url, max_length=2200))
                except Exception:
                    continue
                if not page.startswith("Error:"):
                    snippets.append({"query": query, "url": url, "content": shorten(page, 1600)})
                if len(snippets) >= 3:
                    return snippets
        return snippets

    @staticmethod
    def _queries(profile: dict[str, Any]) -> list[str]:
        queries: list[str] = []
        drivers = profile.get("driver_candidates", [])
        functions = profile.get("functions", [])
        kernel_version = profile.get("kernel_version", "unknown")
        if drivers:
            queries.extend([
                f"Linux kernel {drivers[0]} driver architecture and data path",
                f"docs.kernel.org {drivers[0]} driver design",
            ])
        if functions:
            queries.append(f"Linux kernel function {functions[0]} responsibilities and call chain")
        if kernel_version != "unknown":
            queries.append(f"Linux kernel {kernel_version} subsystem documentation behavior changes")
        queries.append("Linux kernel driver debugging workflow docs.kernel.org")
        return list(dict.fromkeys(queries))


def shorten(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + " ..."
