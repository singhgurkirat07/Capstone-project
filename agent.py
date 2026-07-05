"""
Phoenix Research Agent — Core Agent Logic (v4)
======================================================================
Provides the asynchronous agent execution loop powered by the Gemini API,
complete with Google Search, Web Crawling, File system management, Python
execution, and SQLite database productivity tools.

The Gemini API key is read from the GEMINI_API_KEY environment variable
(see app.py / .env) — it is never passed in from the client, so end users
never need to paste an API key of their own.
"""
import asyncio
import json
import re
import sys
import os
import uuid
import subprocess
from pathlib import Path
import httpx

import db

# Default Gemini model. We explicitly use gemini-2.5-flash because the "latest" 
# alias maps to 3.5, which currently has a very strict 20 request/day free limit.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

WORKSPACE = Path(__file__).resolve().parent

# ── Agent System Prompts & Capabilities ──────────────────────────────
AGENT_CONFIGS = {
    "jarvis": {
        "name": "Phoenix",
        "icon": "🔥",
        "color": "#FF6B35",
        "description": "General AI Orchestrator. Can research, write code, plan tasks, take notes, and search the web.",
        "capabilities": ["General Assistant", "Web Search & Crawling", "File & Directory Operations", "Task & Note Management", "Code Execution"],
        "tools": [
            "web_search", "web_fetch", "read_file", "write_file", "list_directory",
            "execute_python_code", "add_task", "list_tasks", "update_task_status",
            "add_note", "list_notes", "query_knowledge"
        ]
    },
    "coder": {
        "name": "Coder",
        "icon": "💻",
        "color": "#10B981",
        "description": "Software Development Specialist. Reads, writes, debugs, and runs code files in the workspace.",
        "capabilities": ["File & Directory Operations", "Python Code Execution", "Syntax Debugging", "Automated Scripting"],
        "tools": ["read_file", "write_file", "list_directory", "execute_python_code"]
    },
    "researcher": {
        "name": "Researcher",
        "icon": "🔍",
        "color": "#60A5FA",
        "description": "Deep Web Search & Knowledge Base Agent. Gathers and synthesizes facts with inline citations.",
        "capabilities": ["Web Search & Crawling", "Source Cross-Referencing", "Knowledge Base Retrieval (RAG)", "Synthesis Reports"],
        "tools": ["web_search", "web_fetch", "query_knowledge"]
    },
    "planner": {
        "name": "Planner",
        "icon": "📋",
        "color": "#A78BFA",
        "description": "Productivity & Project Planner. Breaks down goals into tasks, schedules, and takes structured notes.",
        "capabilities": ["Task Lifecycle Management", "Project Outline Generation", "Actionable Goal Checklists", "Note Keeping"],
        "tools": ["add_task", "list_tasks", "update_task_status", "add_note", "list_notes"]
    },
    "writer": {
        "name": "Writer",
        "icon": "✍️",
        "color": "#F59E0B",
        "description": "Creative & Technical Document Writer. Excellent at drafting markdown reports and essays.",
        "capabilities": ["Markdown Document Writing", "Technical Documentation", "Copy Editing", "Web Fact-checking"],
        "tools": ["read_file", "write_file", "web_search", "web_fetch"]
    }
}

TOOL_DESCRIPTIONS = {
    "web_search": '{"query": "..."} Search the web for information; returns titles, URLs, and snippets.',
    "web_fetch": '{"url": "..."} Fetch the full text content of a single webpage URL.',
    "read_file": '{"path": "..."} Read the UTF-8 text contents of a file in the workspace.',
    "write_file": '{"path": "...", "content": "..."} Write content to a file in the workspace.',
    "list_directory": '{"path": "..."} List all files and folders in a workspace subdirectory.',
    "execute_python_code": '{"code": "..."} Run a Python code snippet locally and capture stdout/stderr.',
    "add_task": '{"title": "...", "description": "...", "project_id": "...", "priority": "..."} Add a task to the productivity database.',
    "list_tasks": '{"project_id": "..."} List tasks in the database.',
    "update_task_status": '{"task_id": "...", "status": "..."} Update a task\'s status ("todo", "in_progress", "done").',
    "add_note": '{"title": "...", "content": "...", "project_id": "..."} Create a persistent markdown note.',
    "list_notes": '{"project_id": "..."} List all persistent notes.',
    "query_knowledge": '{"query": "..."} Search through uploaded documents and knowledge base chunks.'
}

def get_agent_system_prompt(agent_id: str) -> str:
    config = AGENT_CONFIGS.get(agent_id, AGENT_CONFIGS["jarvis"])
    tools_info = [f"- {t}: {TOOL_DESCRIPTIONS.get(t, '')}" for t in config["tools"]]
    tools_str = "\n".join(tools_info)
    
    return f"""You are {config['name']}, {config['description']}
Running inside a workspace folder: {str(WORKSPACE)}

You are running in an iterative ReAct execution loop.

You have access to the following tools:
{tools_str}

Respond with EXACTLY ONE tool call each turn, formatted exactly like the examples:

TOOL_CALL: web_search {{"query": "latest AI developments"}}

or:

TOOL_CALL: read_file {{"path": "README.md"}}

or:

TOOL_CALL: execute_python_code {{"code": "print('hello world')"}}

Once you have gathered sufficient, factual, and cross-referenced information (or finished performing the requested task), formulate your complete response and output it formatted like this:

FINAL_ANSWER: <your comprehensive answer, plan, or summary for the user. If you are citing facts from web pages or local documents, use inline citation links like [Source Title](url) or [Document Name](doc_name)>

Rules:
1. Respond ONLY with either TOOL_CALL: <name> <json_args> or FINAL_ANSWER: <text>. No extra text before or after.
2. Be objective, precise, and double-check your arguments.
3. Your goal is to complete the user's request using the tools available to you.
You must use a step-by-step reasoning process.

CRITICAL INSTRUCTION FOR ARTIFACTS: 
If the user asks you to create a roadmap, plan, report, or any other artifact, and you use `write_file` to save it, YOU MUST ALSO output the full content of that file inside your FINAL_ANSWER. Do not just say "I saved it to a file." The user's UI only displays your FINAL_ANSWER, so if you don't include the text there, they cannot read it!
4. You have a limited number of steps. Don't loop endlessly. If you have done the task, output FINAL_ANSWER.
"""

# ── Tools Implementation ──────────────────────────────────────────────

async def web_search(query: str, max_results: int = 5) -> str:
    from duckduckgo_search import DDGS
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append((r.get("title", ""), r.get("href", ""), r.get("body", "")))
    except Exception as e:
        return f"Error executing web search: {e}"

    if not results:
        return "No search results found."
    
    lines = [f"Search results for query: {query}\n"]
    for i, (title, url, snippet) in enumerate(results, 1):
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}\n")
    return "\n".join(lines)


async def web_fetch(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Phoenix-AI/3.0"})
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        return f"Error fetching web page: {e}"

    # Clean up HTML structure to extract readable text content
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:8000]


def _safe_path(path: str) -> Path | None:
    """Resolve path and ensure it stays within workspace."""
    try:
        resolved = (WORKSPACE / path).resolve()
        if not str(resolved).startswith(str(WORKSPACE.resolve())):
            return None  # Path traversal attempt
        return resolved
    except Exception:
        return None


async def read_file(path: str) -> str:
    safe = _safe_path(path)
    if not safe:
        return f"Error: Access denied or invalid path: {path}"
    if not safe.exists():
        return f"Error: File not found: {path}"
    if not safe.is_file():
        return f"Error: Target is not a file: {path}"
    try:
        content = safe.read_text(encoding="utf-8", errors="replace")
        return content[:8000]
    except Exception as e:
        return f"Error reading file: {e}"


async def write_file(path: str, content: str) -> str:
    safe = _safe_path(path)
    if not safe:
        return f"Error: Access denied or invalid path: {path}"
    try:
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to file: {path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def list_directory(path: str = ".") -> str:
    safe = _safe_path(path)
    if not safe:
        return f"Error: Access denied or invalid path: {path}"
    if not safe.exists():
        return f"Error: Directory not found: {path}"
    try:
        lines = []
        for item in sorted(safe.iterdir()):
            # Hide system, zip, and cache directories
            if item.name.startswith(('.', '__pycache__')) or item.name in ('project-phoenix-main', 'phoenix.db'):
                continue
            item_type = "DIR" if item.is_dir() else "FILE"
            size_str = f" ({item.stat().st_size} B)" if item.is_file() else ""
            lines.append(f"- [{item_type}] {item.name}{size_str}")
        return "\n".join(lines) if lines else "(Empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


async def execute_python_code(code: str) -> str:
    # Write code to a scratch script and execute it
    scratch_dir = WORKSPACE / "scratch"
    scratch_dir.mkdir(exist_ok=True)
    temp_file = scratch_dir / f"agent_run_{uuid.uuid4().hex[:8]}.py"
    
    try:
        temp_file.write_text(code, encoding="utf-8")
        
        # Start python process asynchronously
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(temp_file),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(WORKSPACE)
        )
        stdout, stderr = await process.communicate()
        
        output = ""
        if stdout:
            output += f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}\n"
        if stderr:
            output += f"STDERR:\n{stderr.decode('utf-8', errors='replace')}\n"
        
        return output if output else "Execution complete (no output)."
    except Exception as e:
        return f"Execution error: {e}"
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass


async def add_task(title: str, description: str = "", project_id: str = "default", priority: str = "medium") -> str:
    try:
        tid = db.create_task(title, description, project_id, priority)
        return f"Task created successfully. Title: '{title}', ID: '{tid}', Project: '{project_id}'"
    except Exception as e:
        return f"Error creating task: {e}"


async def list_tasks(project_id: str = None) -> str:
    try:
        tasks = db.list_tasks(project_id)
        if not tasks:
            return "No tasks found in database."
        lines = []
        for t in tasks:
            proj = f" [Project: {t.get('project_name')}]" if t.get('project_name') else ""
            lines.append(f"- [{t['status'].upper()}] {t['title']} (Priority: {t['priority']}) (ID: {t['id']}){proj}\n  Description: {t['description']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing tasks: {e}"


async def update_task_status(task_id: str, status: str) -> str:
    valid_statuses = ["todo", "in_progress", "done"]
    if status not in valid_statuses:
        return f"Error: Status must be one of {valid_statuses}."
    try:
        db.update_task_status(task_id, status)
        return f"Task '{task_id}' updated successfully to status: '{status}'"
    except Exception as e:
        return f"Error updating task status: {e}"


async def add_note(title: str, content: str, project_id: str = "default") -> str:
    try:
        nid = db.create_note(title, content, project_id)
        return f"Note created successfully. Title: '{title}', ID: '{nid}'"
    except Exception as e:
        return f"Error creating note: {e}"


async def list_notes(project_id: str = None) -> str:
    try:
        notes = db.list_notes(project_id)
        if not notes:
            return "No notes found."
        lines = []
        for n in notes:
            proj = f" [Project: {n.get('project_name')}]" if n.get('project_name') else ""
            lines.append(f"- Note: '{n['title']}' (ID: {n['id']}){proj}\n  Content:\n  {n['content']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing notes: {e}"


async def query_knowledge(query: str) -> str:
    try:
        chunks = db.query_knowledge_chunks(query)
        if not chunks:
            return f"No relevant information found for query: '{query}' in uploaded documents."
        
        lines = ["Matches from local knowledge files:"]
        for i, c in enumerate(chunks, 1):
            lines.append(f"{i}. [Doc: {c['doc_name']}]\n   Content: {c['text']}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"Error querying local knowledge base: {e}"


TOOLS = {
    "web_search": web_search,
    "web_fetch": web_fetch,
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "execute_python_code": execute_python_code,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "update_task_status": update_task_status,
    "add_note": add_note,
    "list_notes": list_notes,
    "query_knowledge": query_knowledge
}

EXPECTED_ARG = {
    "web_search": "query",
    "web_fetch": "url",
    "read_file": "path",
    "write_file": "path",
    "list_directory": "path",
    "execute_python_code": "code",
    "add_task": "title",
    "list_tasks": "project_id",
    "update_task_status": "task_id",
    "add_note": "title",
    "list_notes": "project_id",
    "query_knowledge": "query"
}


def normalize_args(tool_name: str, args: dict) -> dict:
    """Fixes common parameter naming discrepancies in LLM tool outputs."""
    expected = EXPECTED_ARG.get(tool_name)
    if expected and expected not in args and len(args) == 1:
        (_, value), = args.items()
        return {expected: value}
    return args


# ── API Connections ──────────────────────────────────────────────────

async def call_gemini(api_key: str, model: str, messages: list[dict]) -> str:
    """Calls Google AI Studio Gemini API via direct REST HTTP requests."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    contents = []
    system_instruction = None
    
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            system_instruction = {"parts": [{"text": content}]}
        else:
            # Map roles: 'user' or 'model'
            gemini_role = "user" if role == "user" else "model"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": content}]
            })
            
    payload = {"contents": contents}
    if system_instruction:
        payload["systemInstruction"] = system_instruction
        
    payload["generationConfig"] = {
        "temperature": 0.2,
        "maxOutputTokens": 4096
    }
        
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise Exception(f"Gemini API error ({resp.status_code}): {resp.text}")
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise Exception(f"Failed to parse Gemini response payload: {data}")


async def call_ollama(model: str, messages: list[dict]) -> str:
    """Calls a locally running Ollama model."""
    url = "http://localhost:11434/api/chat"
    # Convert messages to Ollama format (role/content pairs)
    ollama_messages = []
    for msg in messages:
        ollama_messages.append({"role": msg["role"], "content": msg["content"]})

    payload = {
        "model": model,
        "messages": ollama_messages,
        "stream": False,
        "options": {"temperature": 0.2}
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            raise Exception(f"Ollama error ({resp.status_code}): {resp.text}")
        data = resp.json()
        return data["message"]["content"]


# ── Response Parser ──────────────────────────────────────────────────

def parse_response(content: str):
    """
    Parses LLM responses robustly, checking for FINAL_ANSWER commands,
    TOOL_CALL lines, and handling potential Markdown JSON block formatting wrappers.
    """
    content_stripped = content.strip()
    
    # 1. Look for FINAL_ANSWER
    if "FINAL_ANSWER:" in content:
        parts = content.split("FINAL_ANSWER:", 1)
        return "FINAL_ANSWER", parts[1].strip()
        
    # 2. Check for TOOL_CALL matches
    tool_call_match = re.search(r"TOOL_CALL:\s*(\w+)\s*(\{.*\})", content, re.DOTALL)
    if tool_call_match:
        tool_name = tool_call_match.group(1)
        json_str = tool_call_match.group(2)
        try:
            return "TOOL_CALL", (tool_name, json.loads(json_str))
        except json.JSONDecodeError:
            pass
            
    # 3. Check for Markdown JSON blocks
    markdown_json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    if markdown_json_match:
        try:
            data = json.loads(markdown_json_match.group(1))
            if isinstance(data, dict):
                if "tool" in data:
                    return "TOOL_CALL", (data["tool"], data.get("args", {}))
                elif "tool_name" in data:
                    return "TOOL_CALL", (data["tool_name"], data.get("args", {}))
        except json.JSONDecodeError:
            pass
            
    # 4. Try parsing whole response as direct JSON
    try:
        data = json.loads(content_stripped)
        if isinstance(data, dict):
            if "tool" in data:
                return "TOOL_CALL", (data["tool"], data.get("args", {}))
            elif "tool_name" in data:
                return "TOOL_CALL", (data["tool_name"], data.get("args", {}))
    except json.JSONDecodeError:
        pass
        
    # 5. Fallback: If no tools are mentioned, assume it's the final answer
    tool_keywords = list(TOOLS.keys())
    has_tool = any(kw in content for kw in tool_keywords)
    if not has_tool:
        return "FINAL_ANSWER", content
        
    return None, None
