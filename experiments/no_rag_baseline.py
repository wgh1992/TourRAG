"""
No-RAG baseline: pure OpenAI LLM, no database, no retrieval.

Use this for comparison experiments. The model answers only from its
parametric knowledge; it cannot return viewpoint_id or in-database names.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Add project root for app.config
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from openai import OpenAI

from app.config import settings

# No-RAG: no database search. Output the attraction name only (from parametric knowledge).
SYSTEM_PROMPT = """You are an assistant for a tourist attraction system. You do NOT have access to any database. Do not search or look up anything.

When the user sends a description of a place or attraction, reply with ONLY the most likely attraction name (one name only). No explanation, no description, no "I cannot look up" — just the name. If unsure, give your best guess as a single name."""


LIST_SYSTEM_PROMPT = """You are an assistant for a tourist attraction system. You do NOT have access to any database. Do not search or look up anything.

When the user sends a description of a place or attraction, reply with up to 10 likely attraction names, ranked from most likely to least likely. Return ONLY a JSON array of strings, with no explanation and no markdown. If unsure, include your best guesses."""


def call_no_rag(query: str, model: str | None = None, language: str = "auto") -> dict:
    """
    Single OpenAI chat completion: no tools, no DB.

    Args:
        query: User question or search text.
        model: OpenAI model (default from settings).
        language: Language hint (currently only affects prompt if needed).

    Returns:
        Dict with keys: answer (str), model (str), usage (dict or None).
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    model = model or settings.OPENAI_MODEL

    user_content = query
    if language and language != "auto":
        user_content = f"[Language: {language}]\n{query}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    answer = (response.choices[0].message.content or "").strip()
    usage = None
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    return {
        "answer": answer,
        "model": model,
        "usage": usage,
    }


def parse_name_list(raw: str, limit: int = 10) -> list[str]:
    """Parse a JSON or line-based list of candidate names from a no-RAG response."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return []

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None

    values: list[str] = []
    if isinstance(parsed, list):
        values = [str(item).strip() for item in parsed]
    elif isinstance(parsed, dict):
        for key in ("candidates", "names", "answers"):
            if isinstance(parsed.get(key), list):
                values = [str(item).strip() for item in parsed[key]]
                break

    if not values:
        values = []
        for line in cleaned.splitlines():
            line = re.sub(r"^\s*(?:[-*]|\d+[\).])\s*", "", line).strip()
            line = line.strip(",;")
            if line:
                values.append(line)

    deduped: list[str] = []
    seen = set()
    for value in values:
        value = value.strip(" \t\r\n\"'")
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
        if len(deduped) >= limit:
            break
    return deduped


def call_no_rag_list(query: str, model: str | None = None, language: str = "auto", limit: int = 10) -> dict:
    """
    Pure LLM No-RAG top-N baseline: no tools, no DB, returns ranked name guesses.
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    model = model or settings.OPENAI_MODEL

    user_content = query
    if language and language != "auto":
        user_content = f"[Language: {language}]\n{query}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": LIST_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    raw = (response.choices[0].message.content or "").strip()
    usage = None
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    return {
        "answers": parse_name_list(raw, limit=limit),
        "raw_answer": raw,
        "model": model,
        "usage": usage,
    }


async def run_no_rag_async(query: str, model: str | None = None, language: str = "auto") -> dict:
    """Async wrapper (runs call_no_rag in executor to avoid blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: call_no_rag(query, model, language))


async def run_no_rag_list_async(
    query: str,
    model: str | None = None,
    language: str = "auto",
    limit: int = 10,
) -> dict:
    """Async wrapper for the ranked no-RAG candidate-list baseline."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: call_no_rag_list(query, model, language, limit))


def main() -> None:
    parser = argparse.ArgumentParser(description="No-RAG baseline: pure LLM, no database.")
    parser.add_argument("--query", required=True, help="User query text.")
    parser.add_argument("--model", default=None, help="OpenAI model (default from config).")
    parser.add_argument("--language", default="auto", help="Language: auto, en, zh.")
    parser.add_argument("--list", action="store_true", help="Return up to 10 ranked name guesses as JSON.")
    args = parser.parse_args()

    if args.list:
        result = call_no_rag_list(args.query, model=args.model, language=args.language)
        print(json.dumps(result["answers"], ensure_ascii=False))
    else:
        result = call_no_rag(args.query, model=args.model, language=args.language)
        print(result["answer"])


if __name__ == "__main__":
    main()
