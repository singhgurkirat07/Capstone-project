"""
Phoenix Research Agent — Capstone Demo (Standalone, Minimal Version)
======================================================================
Self-contained. No dependency on the rest of the Phoenix codebase —
just the Gemini API + DuckDuckGo search + a basic page fetch.
Safer to run/demo under time pressure since nothing else can break it.

The Gemini API key is read from the GEMINI_API_KEY environment variable
(or a local .env file) — nothing to paste in when running the demo.

Setup:
    pip install httpx duckduckgo_search python-dotenv --break-system-packages
    export GEMINI_API_KEY="your-key-here"     # or put it in a .env file

Run:
    python capstone_demo_standalone.py "your question here"
"""
import asyncio
import json
import os
import re
import sys

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
MAX_STEPS = 4

SYSTEM_PROMPT = """You are Phoenix's Research Agent, running in an iterative loop.

You have two tools:
- web_search: {"query": "..."}   search the web, returns titles/urls/snippets
- web_fetch:  {"url": "..."}     fetch and read the full text of one page

Respond with EXACTLY ONE of these each turn, nothing else:

TOOL_CALL: <tool_name> {"arg": "value"}

or, once you have enough information:

FINAL_ANSWER: <complete answer for the user, with inline citations like
[Source: <url>] for every claim>

Rules:
- Search before you fetch. Don't fetch a URL you haven't seen in search results.
- Fetch at least one page before answering, unless the question needs no facts.
- You have a limited number of steps — don't waste them repeating the same search.
"""


# ── Tools ──────────────────────────────────────────────────────────────

async def web_search(query: str, max_results: int = 5) -> str:
    from duckduckgo_search import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append((r.get("title", ""), r.get("href", ""), r.get("body", "")))
    if not results:
        return "No results found."
    lines = [f"Search results for: {query}\n"]
    for i, (title, url, snippet) in enumerate(results, 1):
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}\n")
    return "\n".join(lines)


async def web_fetch(url: str) -> str:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Phoenix-AI/1.0"})
        resp.raise_for_status()
        html = resp.text
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:6000]


TOOLS = {"web_search": web_search, "web_fetch": web_fetch}

EXPECTED_ARG = {"web_search": "query", "web_fetch": "url"}


def normalize_args(tool_name: str, args: dict) -> dict:
    """If the model used the wrong key name (e.g. 'arg' instead of 'query'),
    fix it up rather than failing the call outright."""
    expected = EXPECTED_ARG.get(tool_name)
    if expected and expected not in args and len(args) == 1:
        (_, value), = args.items()
        return {expected: value}
    return args


# ── Minimal Gemini client ────────────────────────────────────────────

async def gemini_chat(client: httpx.AsyncClient, messages: list[dict]) -> str:
    """Calls the Gemini API generateContent endpoint. Converts the simple
    role/content message list into Gemini's contents/systemInstruction shape."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}"

    contents = []
    system_instruction = None
    for msg in messages:
        if msg["role"] == "system":
            # Fold system messages into one systemInstruction (Gemini only
            # accepts a single one), concatenating if there are several.
            text = msg["content"]
            system_instruction = text if system_instruction is None else f"{system_instruction}\n\n{text}"
        else:
            gemini_role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": gemini_role, "parts": [{"text": msg["content"]}]})

    payload = {"contents": contents, "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    resp = await client.post(url, json=payload, timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def parse_tool_call(content: str):
    if not content.strip().startswith("TOOL_CALL:"):
        return None
    body = content.split("TOOL_CALL:", 1)[1].strip()
    match = re.match(r"(\w+)\s+(\{.*\})", body, re.DOTALL)
    if not match:
        return None
    try:
        return match.group(1), json.loads(match.group(2))
    except json.JSONDecodeError:
        return None


# ── Loop ─────────────────────────────────────────────────────────────

async def run_loop(query: str):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    sources: list[str] = []

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY is not set.")
        print('Set it with `export GEMINI_API_KEY="your-key-here"` or put it in a .env file.')
        sys.exit(1)

    async with httpx.AsyncClient() as client:
        for step in range(1, MAX_STEPS + 1):
            if step == MAX_STEPS:
                messages.append({
                    "role": "system",
                    "content": "Last step. Respond with FINAL_ANSWER now using what you have.",
                })

            content = await gemini_chat(client, messages)
            parsed = parse_tool_call(content)

            if parsed is None:
                answer = content.split("FINAL_ANSWER:", 1)[-1].strip()
                print(f"\n[Step {step}] FINAL_ANSWER")
                return answer, sources

            tool_name, args = parsed
            args = normalize_args(tool_name, args)
            print(f"\n[Step {step}] TOOL_CALL: {tool_name}({args})")

            tool_fn = TOOLS.get(tool_name)
            is_error = False
            if tool_fn is None:
                output = f"Unknown tool: {tool_name}"
                is_error = True
            else:
                try:
                    output = await tool_fn(**args)
                except Exception as e:
                    expected = EXPECTED_ARG.get(tool_name, "?")
                    output = (
                        f"Tool error: {e}. The '{tool_name}' tool expects a JSON arg "
                        f'named "{expected}", e.g. TOOL_CALL: {tool_name} {{"{expected}": "..."}}. '
                        f"Try again with the correct argument name — do not answer from memory."
                    )
                    is_error = True

            print(f"           -> {output[:200].strip()}...")

            if tool_name == "web_fetch" and "url" in args:
                if args["url"] not in sources:
                    sources.append(args["url"])
            elif tool_name == "web_search":
                for u in re.findall(r"https?://\S+", output):
                    if u not in sources:
                        sources.append(u)

            messages.append({"role": "assistant", "content": content})
            if is_error:
                next_instruction = "Fix the arguments and issue TOOL_CALL again. Do NOT give FINAL_ANSWER yet — you have no real data."
            else:
                next_instruction = "Next TOOL_CALL, or FINAL_ANSWER if ready."
            messages.append({
                "role": "system",
                "content": f"Tool Result:\n\n{output}\n\n{next_instruction}",
            })

    return "Ran out of steps before a confident answer.", sources


async def main():
    query = " ".join(sys.argv[1:]) or "What are the latest developments in on-device LLMs?"
    print(f"> {query}\n")
    print("Phoenix Research Agent — running loop (max 4 steps)...")
    print("=" * 60)

    answer, sources = await run_loop(query)

    print("\n" + "=" * 60)
    print("\nFINAL ANSWER:\n")
    print(answer)
    if sources:
        print("\nSOURCES:")
        for u in sources:
            print(f"  - {u}")
    else:
        print("\n[WARNING] No sources were fetched — this answer is unverified / from model memory.")


if __name__ == "__main__":
    asyncio.run(main())
