import os
from typing import List, Optional

import httpx
from pydantic import BaseModel


class Source(BaseModel):
    title: str
    link: str
    snippet: Optional[str] = None


def _get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def serper_search(query: str, num: int = 5) -> List[Source]:
    api_key = _get_env("SERPER_API_KEY")
    payload = {"q": query, "num": num}

    with httpx.Client(timeout=20.0) as client:
        r = client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()

    organic = data.get("organic", []) or []
    out: List[Source] = []
    for item in organic[:num]:
        title = item.get("title") or ""
        link = item.get("link") or ""
        snippet = item.get("snippet")
        if title and link:
            out.append(Source(title=title, link=link, snippet=snippet))
    return out
