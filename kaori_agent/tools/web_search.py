"""WebSearch tool: query the Tavily search API."""

import os

from kaori_agent.tools.base import BaseTool, ToolResult

_MAX_RESULTS = 10


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web via Tavily. Returns ranked results with titles, URLs, and snippets, "
        "plus an optional synthesized answer. Use for current events, facts beyond training data, "
        "or any query needing up-to-date information."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "max_results": {
                "type": "integer",
                "description": f"Max results to return (1-{_MAX_RESULTS}). Default: 5.",
            },
            "search_depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": "'basic' (fast, 1 credit) or 'advanced' (deeper, 2 credits). Default: basic.",
            },
            "include_answer": {
                "type": "boolean",
                "description": "Include Tavily's LLM-synthesized answer. Default: true.",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
        **kwargs,
    ) -> ToolResult:
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return ToolResult(
                output="TAVILY_API_KEY not set. Get a key at https://app.tavily.com and add it to .env.",
                is_error=True,
            )

        try:
            from tavily import TavilyClient
        except ImportError:
            return ToolResult(
                output="tavily-python not installed. Run: pip install tavily-python",
                is_error=True,
            )

        max_results = max(1, min(int(max_results), _MAX_RESULTS))

        try:
            client = TavilyClient(api_key=api_key)
            resp = client.search(
                query=query,
                max_results=max_results,
                search_depth=search_depth,
                include_answer=include_answer,
            )
        except Exception as e:
            return ToolResult(output=f"Tavily search error: {e}", is_error=True)

        return ToolResult(output=_format_response(resp))


def _format_response(resp: dict) -> str:
    parts: list[str] = []
    if answer := resp.get("answer"):
        parts.append(f"Answer: {answer}\n")
    for i, r in enumerate(resp.get("results", []), 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        content = (r.get("content") or "").strip()
        parts.append(f"[{i}] {title}\n{url}\n{content}")
    return "\n\n".join(parts) if parts else "(no results)"
