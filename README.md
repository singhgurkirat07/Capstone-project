# Phoenix AI Companion

**Phoenix AI Companion** is an advanced, multi-agent AI research assistant designed for the Google x Kaggle Capstone Project. It goes beyond simple chatbot wrappers by implementing a custom **ReAct (Reasoning and Acting) Agent engine** from scratch, allowing the AI to autonomously utilize tools, search the web, read files, and synthesize information before delivering a final answer.

## ✨ Key Features

### 🧠 Custom ReAct Engine
At the core of the application is a custom-built agent loop that parses LLM responses to execute backend tools. The agent (powered by the "Jarvis" general orchestrator configuration) is capable of autonomous multi-step reasoning (Thought -> Tool Call -> Tool Result -> Final Answer).

### ⚡ Server-Sent Events (SSE) Streaming
Instead of long loading screens, the backend uses SSE to stream the agent's progress in real-time, providing immediate visual feedback as the agent works through complex, multi-step problems.

### 🔄 Dual-Model Support
- **Gemini API Integration:** Built for speed and high-quality reasoning using Google's `gemini-2.5-flash` model (ensuring users get the massive 1,500 requests/day free tier quota without hitting immediate limits).
- **Local Ollama Fallback:** Full support for locally hosted Ollama models (e.g., `qwen3:8b`, `deepseek-coder:6.7b`), ensuring privacy, zero API costs, and offline capabilities. The UI seamlessly adapts to local mode by hiding API usage meters.

### 🗄️ Integrated SQLite Database
A robust backend database tracks and manages:
- **Usage Limits:** Enforces a daily budget for Gemini API calls to prevent unexpected costs.
- **Task Management:** Built-in Kanban-style task tracking.
- **Persistent Notes:** Save important research findings natively in the app.
- **Knowledge Base:** Upload local documents for the agent to reference via chunked indexing.

### 🎨 Cinematic, Premium UI/UX
The frontend is a lightweight Vanilla JS Single Page Application featuring a highly polished, Red Dead Redemption 2 (RDR2) inspired aesthetic. 
- **Dynamic Fire Animations:** Pure CSS keyframe animations respond to the agent's background processing, growing in intensity as the agent thinks and flashing brilliantly upon task completion.
- **Premium Typography:** Final answers are rendered on parchment-styled backgrounds with elegant serif typography.

## 🛠️ Tech Stack
- **Backend:** Python, Flask, SQLite, HTTPX, python-dotenv
- **Frontend:** HTML5, Vanilla JavaScript, CSS3 (Custom Properties, Keyframe Animations, Flexbox)
- **AI Integrations:** Google Gemini API, Local Ollama API, DuckDuckGo Search (ddgs)

## 🚀 Getting Started

### Prerequisites
- Python 3.9+
- A Google Gemini API Key
- Ollama (Optional, for local model support)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/phoenix-ai-companion.git
   cd phoenix-ai-companion
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   Create a `.env` file in the root directory and add your Gemini API key:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```

4. **Run the application:**
   ```bash
   python app.py
   ```

5. **Access the portal:**
   Open your web browser and navigate to `http://127.0.0.1:5000`

## 📂 Project Structure
```text
phoenix-ai-companion/
├── app.py                  # Main Flask application and SSE streaming logic
├── agent.py                # Custom ReAct agent engine and tool implementations
├── db.py                   # SQLite database schemas and query methods
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (API Keys)
├── templates/
│   └── index.html          # Main application layout
└── static/
    ├── css/
    │   └── style.css       # Premium RDR2 styling and dynamic fire animations
    └── js/
        └── app.js          # Frontend state management and SSE event handlers
```

## 🎯 Capstone Highlights
This project demonstrates proficiency in:
1. **Advanced Prompt Engineering & Parsing:** Controlling LLM output formats strictly enough to parse JSON tool arguments reliably.
2. **Asynchronous Python:** Handling long-running agent loops and HTTP requests without blocking the main thread.
3. **Frontend-Backend Synchronization:** Using SSE to keep a complex UI perfectly synced with the backend's internal state machine.
