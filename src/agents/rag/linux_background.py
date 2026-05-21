import re
from typing import Any
from agents.tools.WebSearch import fetch_webpage_content, web_search

URL_RE = re.compile(r"https?://[^\s)]+")
AUTHORITATIVE_DOMAINS = [
    "docs.kernel.org",
    "kernel.org",
    "lore.kernel.org",
    "git.kernel.org",
]
PREFERRED_URL_KEYWORDS = (
    "docs.kernel.org",
    "kernel.org/doc",
    "lore.kernel.org",
    "git.kernel.org",
)


class LinuxBackgroundCollector:
    """Optionally collect a few Linux documentation snippets for the crash profile."""

    def __init__(self, logger: Any) -> None:
        self.logger = logger

    def collect(self, profile: dict[str, Any]) -> list[dict[str, str]]:
        snippets: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        queries = self._build_queries(profile)

        for query, include_domains in self._build_search_plan(queries):
            try:
                result_text = str(
                    web_search.func(
                        query=query,
                        max_results=3,
                        search_depth="advanced",
                        include_domains=include_domains,
                    )
                )
            except Exception as exc:
                self.logger.warning("web_search failed: %s", exc)
                continue
            if "TAVILY_API_KEY" in result_text:
                return []
            if result_text.startswith("Error:"):
                continue
            urls = self._order_urls(URL_RE.findall(result_text))
            for url in urls[:3]:
                if url in seen_urls:
                    continue
                try:
                    page = str(fetch_webpage_content.func(url=url, max_length=2200))
                except Exception:
                    continue
                if not page.startswith("Error:"):
                    seen_urls.add(url)
                    snippets.append({"query": query, "url": url, "content": shorten(page, 1600)})
                if len(snippets) >= 3:
                    return snippets
        return snippets

    def _build_queries(self, profile: dict[str, Any]) -> list[str]:
        drivers = [str(item).strip() for item in profile.get("driver_candidates", []) if item]
        modules = [str(item).strip() for item in profile.get("modules", []) if item]
        functions = [str(item).strip() for item in profile.get("functions", []) if item]
        bug_type = str(profile.get("bug_type", "unknown")).strip()
        kernel_version = str(profile.get("kernel_version", "unknown")).strip()

        targets = list(dict.fromkeys(modules + drivers))[:2]
        queries: list[str] = []

        for target in targets:
            queries.append(
                f"Linux kernel {target} subsystem overview architecture responsibilities documentation"
            )
            if functions:
                queries.append(
                    f"Linux kernel {target} {functions[0]} function role behavior implementation"
                )
            if bug_type and bug_type != "unknown":
                queries.append(
                    f"Linux kernel {target} {bug_type} bug analysis patch discussion"
                )

        if not targets and functions:
            queries.append(
                f"Linux kernel {functions[0]} kernel subsystem role behavior implementation"
            )
            if bug_type and bug_type != "unknown":
                queries.append(
                    f"Linux kernel {functions[0]} {bug_type} bug analysis patch discussion"
                )

        if targets and kernel_version and kernel_version != "unknown":
            queries.append(
                f"Linux kernel {kernel_version} {targets[0]} subsystem changes patch discussion"
            )

        return list(dict.fromkeys(query for query in queries if query))[:4]

    def _build_search_plan(self, queries: list[str]) -> list[tuple[str, list[str]]]:
        plan: list[tuple[str, list[str]]] = []
        for query in queries[:3]:
            plan.append((query, AUTHORITATIVE_DOMAINS))
        for query in queries[:2]:
            plan.append((query, []))
        return plan

    def _order_urls(self, urls: list[str]) -> list[str]:
        ordered = sorted(
            dict.fromkeys(urls),
            key=lambda url: (
                0 if any(keyword in url for keyword in PREFERRED_URL_KEYWORDS) else 1,
                len(url),
            ),
        )
        return ordered


def shorten(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + " ..."
