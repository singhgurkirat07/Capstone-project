"""
Phoenix Research Portal — Flask Web Server (v4)
======================================================================
Serves the web application frontend and exposes the streaming Server-Sent Events
(SSE) API that executes the autonomous research agent loop. Supports Projects,
Tasks, Notes, and File Ingestion (RAG) REST endpoints.

LLM backend: Gemini API only. The API key lives server-side in the
GEMINI_API_KEY environment variable (loaded from a local .env file that is
NOT committed to git — see .env.example). Users of the app never see or
enter an API key.
"""
import asyncio
import json
import queue
import re
import sys
import os
import threading
import uuid
from flask import Flask, Response, request, render_template, jsonify, send_from_directory
from flask_cors import CORS
import httpx
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    # python-dotenv is optional — if it's missing we just rely on real
    # environment variables (e.g. set by the hosting platform).
    pass

# Import modules
import agent
import db

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# ── Gemini configuration (server-side only) ───────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", agent.DEFAULT_GEMINI_MODEL)

if not GEMINI_API_KEY:
    print("=" * 60)
    print("  WARNING: GEMINI_API_KEY is not set.")
    print("  Create a .env file (see .env.example) or set the")
    print("  environment variable before running the agent.")
    print("=" * 60)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ── RAG PDF / File Ingestion Helpers ─────────────────────────────────

def extract_text_from_pdf(filepath):
    """Dual-library PDF text extraction helper."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(filepath)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        return text
    except ImportError:
        try:
            import pypdf
            reader = pypdf.PdfReader(filepath)
            text = ""
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
            return text
        except ImportError:
            raise Exception("Neither PyMuPDF (pymupdf) nor pypdf is installed. Please install them to parse PDF files.")


def chunk_text(text, chunk_size=1000, overlap=150):
    """Breaks down text content into overlapping segments for index searching."""
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])
        if end == text_len:
            break
        start += chunk_size - overlap
    return chunks

# ── Agent Thread Loop ──────────────────────────────────────────────────

async def run_agent_loop_async(q: queue.Queue, query: str, model: str, max_steps: int, agent_id: str, model_type: str = "gemini", local_model: str = ""):
    """Asynchronous agent engine that executes step-by-step and queues UI events."""
    agent_config = agent.AGENT_CONFIGS.get(agent_id, agent.AGENT_CONFIGS["jarvis"])
    system_prompt = agent.get_agent_system_prompt(agent_id)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]
    sources = []

    # The key lives server-side — if it's missing, fail fast with a clear message
    # rather than asking the user to paste one in.
    if model_type != "local" and not GEMINI_API_KEY:
        q.put({"event": "error", "data": "Server misconfiguration: GEMINI_API_KEY is not set. Contact the app administrator."})
        return

    for step in range(1, max_steps + 1):
        q.put({"event": "step_start", "data": {"step": step, "max_steps": max_steps}})

        # Request final answer if it's the last step
        if step == max_steps:
            messages.append({
                "role": "user",
                "content": "SYSTEM ALERT: This is the LAST step. Do not call tools. Formulate and output your FINAL_ANSWER now using the information you have gathered.",
            })

        try:
            if model_type == "local" and local_model:
                content = await agent.call_ollama(local_model, messages)
            else:
                content = await agent.call_gemini(GEMINI_API_KEY, model, messages)
        except Exception as e:
            q.put({"event": "error", "data": f"LLM Connection Error: {str(e)}"})
            return

        # Push thought event to timeline
        q.put({"event": "thought", "data": {"step": step, "content": content}})

        # Parse tool call or final answer
        tool_type, parsed = agent.parse_response(content)

        if tool_type == "FINAL_ANSWER" or tool_type is None:
            answer = parsed if parsed else content
            if "FINAL_ANSWER:" in answer:
                answer = answer.split("FINAL_ANSWER:", 1)[-1].strip()
            q.put({"event": "final_answer", "data": {"answer": answer, "sources": sources}})
            return

        # Execute tool call
        tool_name, tool_args = parsed
        tool_args = agent.normalize_args(tool_name, tool_args)

        q.put({"event": "tool_call", "data": {"step": step, "tool": tool_name, "args": tool_args}})

        # Verify tool permissions for the active agent
        if tool_name not in agent_config["tools"]:
            output = f"Error: Tool '{tool_name}' is not in the permitted tool list for your role as '{agent_config['name']}'."
            is_error = True
        else:
            tool_fn = agent.TOOLS.get(tool_name)
            is_error = False

            if tool_fn is None:
                output = f"Error: Tool '{tool_name}' is not recognized by the system."
                is_error = True
            else:
                try:
                    # Call asynchronous tool function
                    output = await tool_fn(**tool_args)
                except Exception as e:
                    expected_param = agent.EXPECTED_ARG.get(tool_name, "arg")
                    output = (
                        f"Error: {e}. The tool '{tool_name}' requires parameters matching: {expected_param}. "
                        f"Please retry formatting your request correctly: TOOL_CALL: {tool_name} {{\"{expected_param}\": \"...\"}}"
                    )
                    is_error = True

        # Send tool output to UI (truncated for stability if very large)
        ui_output = output[:4000] + "\n...[truncated for display]..." if len(output) > 4000 else output
        q.put({"event": "tool_result", "data": {"step": step, "tool": tool_name, "output": ui_output}})

        # Store sources (unique list of URLs or local doc matches)
        if tool_name == "web_fetch" and "url" in tool_args:
            url = tool_args["url"]
            if url not in sources:
                sources.append(url)
        elif tool_name == "web_search":
            found_urls = re.findall(r"https?://\S+", output)
            for url in found_urls:
                url = re.sub(r"[.,);]$", "", url)  # clean up trailing punctuation
                if url not in sources:
                    sources.append(url)
        elif tool_name == "query_knowledge":
            found_docs = re.findall(r"\[Doc:\s*(.*?)\]", output)
            for doc in found_docs:
                doc_label = f"Local Doc: {doc}"
                if doc_label not in sources:
                    sources.append(doc_label)

        # Record turn in conversation history
        messages.append({"role": "assistant", "content": content})

        # Format system feedback for next cycle
        system_feedback = f"Tool Result:\n\n{output}\n\n"
        if is_error:
            system_feedback += "Please correct the tool arguments."
        else:
            system_feedback += "Review this tool result. Continue your ReAct execution loop or formulate your FINAL_ANSWER."

        messages.append({"role": "user", "content": system_feedback})

    # Ran out of steps fallback
    q.put({
        "event": "final_answer",
        "data": {
            "answer": "The agent execution loop completed the maximum allocated steps but did not output an explicit final answer. Below is a summary of facts or sources found.\n\n" +
                      "\n".join([f"- {url}" for url in sources]) if sources else "No information was successfully fetched.",
            "sources": sources
        }
    })


def start_agent_thread(q: queue.Queue, query: str, model: str, max_steps: int, agent_id: str, model_type: str = "gemini", local_model: str = ""):
    """Target function to spawn the asyncio event loop inside a separate background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_agent_loop_async(q, query, model, max_steps, agent_id, model_type, local_model))
    except Exception as e:
        q.put({"event": "error", "data": f"Internal Runner Exception: {str(e)}"})
    finally:
        q.put({"event": "done", "data": {}})
        loop.close()


# ── Web Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Renders the dashboard single page application."""
    return render_template("index.html")


@app.route("/api/research")
def api_research():
    """
    Server-Sent Events endpoint that triggers the research loop
    and yields updates in real time to the browser. Uses the server-side
    Gemini API key — the client never sends one.
    """
    query = request.args.get("query", "")
    model = request.args.get("model", GEMINI_MODEL)
    max_steps = int(request.args.get("max_steps", "5"))
    agent_id = request.args.get("agent", "jarvis")
    model_type = request.args.get("model_type", "gemini")
    local_model = request.args.get("local_model", "")

    if not query:
        return jsonify({"error": "Query parameter is required"}), 400

    # Check usage limits before starting only for Gemini API
    if model_type == "gemini":
        if not db.increment_usage():
            return jsonify({"error": "Daily usage limit reached. Try again tomorrow or increase your limit."}), 429

    q = queue.Queue()

    # Spawn research engine thread
    thread = threading.Thread(
        target=start_agent_thread,
        args=(q, query, model, max_steps, agent_id, model_type, local_model)
    )
    thread.daemon = True
    thread.start()

    def sse_event_stream():
        """Generator that pulls events from the queue and yields them in SSE format."""
        while True:
            try:
                item = q.get(timeout=1.0)
                event = item["event"]
                data = item["data"]
                
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                
                if event == "done":
                    break
            except queue.Empty:
                if not thread.is_alive():
                    yield f"event: done\ndata: {json.dumps({})}\n\n"
                    break
                continue
            except Exception as e:
                yield f"event: error\ndata: {json.dumps(f'Stream exception: {str(e)}')}\n\n"
                break

    return Response(sse_event_stream(), mimetype="text/event-stream")


@app.route("/api/health")
def api_health():
    """Simple healthcheck to verify Flask backend status and Gemini configuration."""
    return jsonify({
        "status": "online",
        "message": "Phoenix Research Portal backend is operational.",
        "gemini_configured": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL,
    })


@app.route("/api/agents")
def api_get_agents():
    """Returns the available agent configurations in a JSON-friendly format."""
    return jsonify(agent.AGENT_CONFIGS)


@app.route("/api/usage")
def api_get_usage():
    """Returns today's usage stats."""
    return jsonify(db.get_today_usage())


@app.route("/api/local-models")
def api_get_local_models():
    """Lists locally installed Ollama models. Returns empty list if Ollama is not running."""
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "modified_at": m.get("modified_at", ""),
                })
            return jsonify({"available": True, "models": models})
        else:
            return jsonify({"available": False, "models": []})
    except Exception:
        return jsonify({"available": False, "models": []})


# ── Projects API ──────────────────────────────────────────────────────

@app.route("/api/projects", methods=["GET"])
def api_get_projects():
    return jsonify(db.list_projects())


@app.route("/api/projects", methods=["POST"])
def api_post_project():
    data = request.json or {}
    name = data.get("name")
    description = data.get("description", "")
    if not name:
        return jsonify({"error": "Project name is required"}), 400
    pid = db.create_project(name, description)
    return jsonify({"success": True, "id": pid})


@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_delete_project(pid):
    success = db.delete_project(pid)
    return jsonify({"success": success})


# ── Tasks API ─────────────────────────────────────────────────────────

@app.route("/api/tasks", methods=["GET"])
def api_get_tasks():
    project_id = request.args.get("project_id")
    return jsonify(db.list_tasks(project_id))


@app.route("/api/tasks", methods=["POST"])
def api_post_task():
    data = request.json or {}
    title = data.get("title")
    description = data.get("description", "")
    project_id = data.get("project_id", "default")
    priority = data.get("priority", "medium")
    status = data.get("status", "todo")
    
    if not title:
        return jsonify({"error": "Task title is required"}), 400
    tid = db.create_task(title, description, project_id, priority, status)
    return jsonify({"success": True, "id": tid})


@app.route("/api/tasks/<tid>/status", methods=["PUT"])
def api_update_task_status(tid):
    data = request.json or {}
    status = data.get("status")
    if not status:
        return jsonify({"error": "Status is required"}), 400
    db.update_task_status(tid, status)
    return jsonify({"success": True})


@app.route("/api/tasks/<tid>", methods=["DELETE"])
def api_delete_task(tid):
    db.delete_task(tid)
    return jsonify({"success": True})


# ── Notes API ─────────────────────────────────────────────────────────

@app.route("/api/notes", methods=["GET"])
def api_get_notes():
    project_id = request.args.get("project_id")
    return jsonify(db.list_notes(project_id))


@app.route("/api/notes", methods=["POST"])
def api_post_note():
    data = request.json or {}
    title = data.get("title")
    content = data.get("content")
    project_id = data.get("project_id", "default")
    note_type = data.get("type", "note")
    
    if not content:
        return jsonify({"error": "Note content is required"}), 400
    nid = db.create_note(title, content, project_id, note_type)
    return jsonify({"success": True, "id": nid})


@app.route("/api/notes/<nid>", methods=["DELETE"])
def api_delete_note(nid):
    db.delete_note(nid)
    return jsonify({"success": True})


# ── Knowledge / File Upload API ───────────────────────────────────────

@app.route("/api/knowledge", methods=["GET"])
def api_get_knowledge():
    return jsonify(db.list_knowledge_docs())


@app.route("/api/knowledge/upload", methods=["POST"])
def api_upload_knowledge():
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
        
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    file_size = os.path.getsize(filepath)
    file_type = filename.split('.')[-1].lower()
    
    # Process text content based on file extension
    try:
        if file_type == 'pdf':
            content = extract_text_from_pdf(filepath)
        elif file_type in ['txt', 'md']:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        else:
            return jsonify({"error": f"Unsupported file type: {file_type}. Supported: PDF, TXT, MD"}), 400
            
        # Chunk text
        chunks = chunk_text(content)
        if not chunks:
            chunks = ["Empty document content."]
            
        doc_id = db.add_knowledge_doc(filename, filepath, file_type, file_size, chunks)
        return jsonify({"success": True, "id": doc_id, "chunks": len(chunks)})
        
    except Exception as e:
        return jsonify({"error": f"Failed to ingest file: {str(e)}"}), 500


@app.route("/api/knowledge/<doc_id>", methods=["DELETE"])
def api_delete_knowledge(doc_id):
    # Retrieve file path to remove it from disk
    conn = db.get_db_connection()
    doc = conn.execute("SELECT file_path FROM knowledge_docs WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    
    if doc:
        filepath = doc["file_path"]
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
                
    db.delete_knowledge_doc(doc_id)
    return jsonify({"success": True})


@app.route("/api/knowledge/query", methods=["GET"])
def api_query_knowledge():
    query_text = request.args.get("query", "")
    if not query_text:
        return jsonify({"error": "Query parameter is required"}), 400
    results = db.query_knowledge_chunks(query_text)
    return jsonify(results)


if __name__ == "__main__":
    print("=" * 60)
    print("  Phoenix Research Portal Server running at: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=True)
