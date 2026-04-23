"""
No-RAG baseline: pure OpenAI LLM, no database, no retrieval.

Use this for comparison experiments. The model answers only from its
parametric knowledge; it cannot return viewpoint_id or in-database names.
"""
import argparse
import asyncio
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


async def run_no_rag_async(query: str, model: str | None = None, language: str = "auto") -> dict:
    """Async wrapper (runs call_no_rag in executor to avoid blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: call_no_rag(query, model, language))


def main() -> None:
    parser = argparse.ArgumentParser(description="No-RAG baseline: pure LLM, no database.")
    parser.add_argument("--query", required=True, help="User query text.")
    parser.add_argument("--model", default=None, help="OpenAI model (default from config).")
    parser.add_argument("--language", default="auto", help="Language: auto, en, zh.")
    args = parser.parse_args()

    result = call_no_rag(args.query, model=args.model, language=args.language)
    print(result["answer"])


if __name__ == "__main__":
    main()
