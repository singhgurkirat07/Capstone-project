/* ================================================================
   Phoenix Research Portal — Main Application JS
   ================================================================ */

(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────
  const state = {
    currentAgent: 'jarvis',
    modelType: 'gemini',      // 'gemini' or 'local'
    localModel: '',
    isStreaming: false,
    usage: { used: 0, limit: 50, remaining: 50, percentage: 0 },
    openPanel: null,
  };

  // ── DOM References ─────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const heroSection = $('#heroSection');
  const chatSection = $('#chatSection');
  const chatMessages = $('#chatMessages');
  const heroInput = $('#heroInput');
  const heroSend = $('#heroSend');
  const chatInput = $('#chatInput');
  const chatSend = $('#chatSend');
  const usageBarFill = $('#usageBarFill');
  const usageText = $('#usageText');
  const localModelSelect = $('#localModelSelect');
  const panelOverlay = $('#panelOverlay');
  const usageWarning = $('#usageWarning');
  const usageMeter = $('#usageMeter'); // Added reference to usage meter

  // ── Init ───────────────────────────────────────────────────────
  async function init() {
    setupModelToggle();
    setupChatInputs();
    setupPanels();
    setupNavIcons();
    setupUpload();

    await Promise.all([
      fetchUsage(),
      fetchLocalModels(),
    ]);

    // Poll usage every 30s
    setInterval(fetchUsage, 30000);
  }

  // ── Model Toggle ───────────────────────────────────────────────
  function setupModelToggle() {
    $$('.model-option').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.model-option').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.modelType = btn.dataset.model;

        if (state.modelType === 'local') {
          localModelSelect.style.display = 'inline-block';
          usageMeter.style.opacity = '0'; // Hide usage meter smoothly
          usageMeter.style.pointerEvents = 'none';
          fetchLocalModels();
        } else {
          localModelSelect.style.display = 'none';
          usageMeter.style.opacity = '1';
          usageMeter.style.pointerEvents = 'auto';
        }
      });
    });

    localModelSelect.addEventListener('change', (e) => {
      state.localModel = e.target.value;
    });
  }

  // ── Chat Input Setup ───────────────────────────────────────────
  function setupChatInputs() {
    // Auto-resize textareas
    [heroInput, chatInput].forEach(input => {
      input.addEventListener('input', () => autoResize(input));
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendMessage(input.value.trim());
          input.value = '';
          autoResize(input);
        }
      });
    });

    heroSend.addEventListener('click', () => {
      sendMessage(heroInput.value.trim());
      heroInput.value = '';
      autoResize(heroInput);
    });

    chatSend.addEventListener('click', () => {
      sendMessage(chatInput.value.trim());
      chatInput.value = '';
      autoResize(chatInput);
    });
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }

  // ── Send Message & SSE Stream ──────────────────────────────────
  function sendMessage(query) {
    if (!query || state.isStreaming) return;

    // Check usage limit
    if (state.modelType === 'gemini' && state.usage.remaining <= 0) {
      usageWarning.classList.add('visible');
      return;
    }

    // Switch to chat view
    if (heroSection.style.display !== 'none') {
      heroSection.style.display = 'none';
      chatSection.style.display = 'flex';
      chatInput.focus();
    }

    // Add user message
    addMessage('user', query, '👤');

    // Start streaming
    state.isStreaming = true;
    setSendDisabled(true);

    // Show thinking indicator
    const thinkingEl = addThinking();

    // Build SSE URL
    const params = new URLSearchParams({
      query: query,
      agent: state.currentAgent,
      max_steps: '5',
      model_type: state.modelType,
    });

    if (state.modelType === 'local' && state.localModel) {
      params.set('local_model', state.localModel);
    }

    const centerFire = document.getElementById('center-fire-container');
    centerFire.classList.remove('fire-extinguish');
    centerFire.classList.add('active');
    document.documentElement.style.setProperty('--search-fire-scale', '1');

    const evtSource = new EventSource('/api/research?' + params.toString());
    let currentStepsContainer = null;

    // Create a container for this response
    const responseContainer = document.createElement('div');
    responseContainer.className = 'message';
    const agentConfig = getAgentConfig(state.currentAgent);
    responseContainer.innerHTML = `
      <div class="message-avatar agent" style="border-color:${agentConfig.color}">${agentConfig.icon}</div>
      <div class="message-body">
        <div class="message-sender">${agentConfig.name}</div>
        <div class="message-steps"></div>
        <div class="message-answer" style="display:none"></div>
      </div>
    `;
    chatMessages.appendChild(responseContainer);
    currentStepsContainer = responseContainer.querySelector('.message-steps');
    const answerContainer = responseContainer.querySelector('.message-answer');

    // Remove thinking when first event arrives
    let thinkingRemoved = false;
    function removeThinking() {
      if (!thinkingRemoved && thinkingEl.parentNode) {
        thinkingEl.remove();
        thinkingRemoved = true;
      }
    }

    evtSource.addEventListener('step_start', (e) => {
      const data = JSON.parse(e.data);
      const scale = 1 + (data.step * 0.3);
      document.documentElement.style.setProperty('--search-fire-scale', scale);
    });

    evtSource.addEventListener('thought', (e) => {});
    evtSource.addEventListener('tool_call', (e) => {});
    evtSource.addEventListener('tool_result', (e) => {});

    evtSource.addEventListener('final_answer', (e) => {
      removeThinking();
      const data = JSON.parse(e.data);
      
      centerFire.classList.add('fire-flash');
      
      setTimeout(() => {
        centerFire.classList.add('fire-extinguish');
        centerFire.classList.remove('fire-flash');
        centerFire.classList.remove('active');
        document.documentElement.style.setProperty('--search-fire-scale', '1');
        
        answerContainer.style.display = 'block';
        answerContainer.innerHTML = `<div class="message-content">${formatMarkdown(data.answer)}</div>`;

        if (data.sources && data.sources.length > 0) {
          const sourceHtml = `
            <div class="sources-list">
              <div class="sources-title">Sources</div>
              ${data.sources.map(s => {
                if (s.startsWith('http')) {
                  return `<div class="source-item"><a href="${escapeHtml(s)}" target="_blank" rel="noopener">${escapeHtml(s)}</a></div>`;
                }
                return `<div class="source-item">${escapeHtml(s)}</div>`;
              }).join('')}
            </div>
          `;
          answerContainer.innerHTML += sourceHtml;
        }

        scrollToBottom();
      }, 800);
    });

    evtSource.addEventListener('error', (e) => {
      removeThinking();
      centerFire.classList.remove('active');
      let errMsg = 'An error occurred';
      if (e.data) {
        try { errMsg = JSON.parse(e.data); } catch { errMsg = e.data; }
      }
      answerContainer.style.display = 'block';
      answerContainer.innerHTML = `<div class="message-content" style="color:var(--red)">${escapeHtml(String(errMsg))}</div>`;
      scrollToBottom();
    });

    evtSource.addEventListener('done', () => {
      removeThinking();
      evtSource.close();
      state.isStreaming = false;
      setSendDisabled(false);
      fetchUsage(); 
    });

    evtSource.onerror = () => {
      removeThinking();
      centerFire.classList.remove('active');
      evtSource.close();
      state.isStreaming = false;
      setSendDisabled(false);

      if (answerContainer.style.display === 'none') {
        answerContainer.style.display = 'block';
        if (state.modelType === 'gemini') {
          answerContainer.innerHTML = '<div class="message-content" style="color:var(--red)">Connection lost. Make sure the Gemini API key is set in the .env file and the server is running.</div>';
        } else {
          answerContainer.innerHTML = '<div class="message-content" style="color:var(--red)">Connection lost. Make sure Ollama is running locally with the selected model.</div>';
        }
      }
      scrollToBottom();
    };
  }

  function setSendDisabled(disabled) {
    heroSend.disabled = disabled;
    chatSend.disabled = disabled;
  }

  function addMessage(role, content, avatar) {
    const div = document.createElement('div');
    div.className = 'message';
    div.innerHTML = `
      <div class="message-avatar ${role}">${avatar}</div>
      <div class="message-body">
        <div class="message-sender">${role === 'user' ? 'You' : ''}</div>
        <div class="message-content">${escapeHtml(content)}</div>
      </div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function addThinking() {
    const div = document.createElement('div');
    div.className = 'thinking';
    const agentConfig = getAgentConfig(state.currentAgent);
    div.innerHTML = `
      <span>${agentConfig.icon}</span>
      <span>${agentConfig.name} is thinking</span>
      <div class="thinking-dots">
        <span></span><span></span><span></span>
      </div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function createStepCard(type, label, content) {
    const card = document.createElement('div');
    card.className = 'step-card';
    card.innerHTML = `
      <div class="step-header">
        <span class="step-badge ${type}">${getStepIcon(type)} ${escapeHtml(label)}</span>
      </div>
      <div class="step-content collapsed">${escapeHtml(content)}</div>
    `;
    card.querySelector('.step-content').addEventListener('click', function () {
      this.classList.toggle('collapsed');
    });
    return card;
  }

  function getStepIcon(type) {
    switch (type) {
      case 'thought': return '💭';
      case 'tool': return '🔧';
      case 'result': return '📋';
      case 'error': return '⚠️';
      default: return '•';
    }
  }

  function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // ── Agent Configs ──────────────────────────────────────────────
  const AGENT_CONFIGS = {
    jarvis: { name: 'Jarvis', icon: '🔥', color: '#FF6B35' },
    coder: { name: 'Coder', icon: '💻', color: '#10B981' },
    researcher: { name: 'Researcher', icon: '🔍', color: '#60A5FA' },
    planner: { name: 'Planner', icon: '📋', color: '#A78BFA' },
    writer: { name: 'Writer', icon: '✍️', color: '#F59E0B' },
  };

  function getAgentConfig(id) {
    return AGENT_CONFIGS[id] || AGENT_CONFIGS.jarvis;
  }

  // ── Usage ──────────────────────────────────────────────────────
  async function fetchUsage() {
    try {
      const resp = await fetch('/api/usage');
      const data = await resp.json();
      state.usage = data;
      updateUsageUI();
    } catch (e) {
      console.error('Failed to fetch usage:', e);
    }
  }

  function updateUsageUI() {
    const { used, limit, remaining, percentage } = state.usage;
    usageBarFill.style.width = percentage + '%';

    // Shift gradient based on usage
    usageBarFill.style.backgroundPosition = percentage + '% 0';
    usageText.textContent = `${used}/${limit}`;

    // Update fire intensity based on usage percentage
    const fireIntensity = Math.min(percentage / 100, 1);
    document.documentElement.style.setProperty('--fire-intensity', fireIntensity);

    // Add pulsing glow when approaching limit
    if (percentage > 80) {
      usageText.style.color = 'var(--red)';
    } else if (percentage > 50) {
      usageText.style.color = 'var(--gold)';
    } else {
      usageText.style.color = 'var(--text-muted)';
    }
  }

  // ── Local Models ───────────────────────────────────────────────
  async function fetchLocalModels() {
    try {
      const resp = await fetch('/api/local-models');
      const data = await resp.json();

      localModelSelect.innerHTML = '';

      if (data.available && data.models.length > 0) {
        data.models.forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.name || m;
          opt.textContent = m.name || m;
          localModelSelect.appendChild(opt);
        });
        state.localModel = localModelSelect.value;
      } else {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'No models found';
        localModelSelect.appendChild(opt);
      }
    } catch (e) {
      console.error('Failed to fetch local models:', e);
      localModelSelect.innerHTML = '<option value="">Ollama offline</option>';
    }
  }

  // ── Nav Icons & Panels ─────────────────────────────────────────
  function setupNavIcons() {
    $$('.nav-icon-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const panelId = btn.dataset.panel;
        if (state.openPanel === panelId) {
          closePanel();
        } else {
          openPanel(panelId);
        }
      });
    });

    panelOverlay.addEventListener('click', closePanel);
  }

  function setupPanels() {
    $$('[data-close-panel]').forEach(btn => {
      btn.addEventListener('click', closePanel);
    });

    // Tasks
    $('#addTaskBtn').addEventListener('click', () => {
      $('#taskForm').classList.toggle('open');
    });
    $('#taskCancel').addEventListener('click', () => {
      $('#taskForm').classList.remove('open');
    });
    $('#taskSubmit').addEventListener('click', submitTask);

    // Notes
    $('#addNoteBtn').addEventListener('click', () => {
      $('#noteForm').classList.toggle('open');
    });
    $('#noteCancel').addEventListener('click', () => {
      $('#noteForm').classList.remove('open');
    });
    $('#noteSubmit').addEventListener('click', submitNote);
  }

  function openPanel(panelId) {
    closePanel(); // Close any open panel first
    const panel = $(`#panel-${panelId}`);
    if (panel) {
      panel.classList.add('open');
      panelOverlay.classList.add('visible');
      state.openPanel = panelId;

      // Update active state on nav icons
      $$('.nav-icon-btn').forEach(b => b.classList.toggle('active', b.dataset.panel === panelId));

      // Load data
      if (panelId === 'tasks') loadTasks();
      if (panelId === 'notes') loadNotes();
      if (panelId === 'knowledge') loadKnowledge();
    }
  }

  function closePanel() {
    $$('.side-panel').forEach(p => p.classList.remove('open'));
    panelOverlay.classList.remove('visible');
    $$('.nav-icon-btn').forEach(b => b.classList.remove('active'));
    state.openPanel = null;
  }

  // ── Tasks CRUD ─────────────────────────────────────────────────
  async function loadTasks() {
    try {
      const resp = await fetch('/api/tasks');
      const tasks = await resp.json();
      const list = $('#taskList');
      list.innerHTML = '';

      if (tasks.length === 0) {
        list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dim);font-family:var(--font-ui);font-size:0.8rem;">No tasks yet</div>';
        return;
      }

      tasks.forEach(t => {
        const card = document.createElement('div');
        card.className = 'panel-card';
        card.innerHTML = `
          <div class="panel-card-header">
            <span class="panel-card-title">${escapeHtml(t.title)}</span>
            <div style="display:flex;gap:6px;align-items:center">
              <span class="priority-badge ${t.priority}">${t.priority}</span>
              <button class="btn-danger" data-delete-task="${t.id}" title="Delete">✕</button>
            </div>
          </div>
          ${t.description ? `<div class="panel-card-body">${escapeHtml(t.description)}</div>` : ''}
          <div style="margin-top:8px;display:flex;gap:4px">
            ${['todo', 'in_progress', 'done'].map(s =>
              `<button class="btn ${t.status === s ? 'btn-primary' : 'btn-ghost'}" style="font-size:0.6rem;padding:3px 8px" data-status-task="${t.id}" data-status="${s}">${s.replace('_', ' ')}</button>`
            ).join('')}
          </div>
        `;
        list.appendChild(card);
      });

      // Wire up status buttons
      list.querySelectorAll('[data-status-task]').forEach(btn => {
        btn.addEventListener('click', async () => {
          await fetch(`/api/tasks/${btn.dataset.statusTask}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: btn.dataset.status }),
          });
          loadTasks();
        });
      });

      // Wire up delete buttons
      list.querySelectorAll('[data-delete-task]').forEach(btn => {
        btn.addEventListener('click', async () => {
          await fetch(`/api/tasks/${btn.dataset.deleteTask}`, { method: 'DELETE' });
          loadTasks();
        });
      });

    } catch (e) {
      console.error('Failed to load tasks:', e);
    }
  }

  async function submitTask() {
    const title = $('#taskTitle').value.trim();
    if (!title) return;

    await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        description: $('#taskDesc').value.trim(),
        priority: $('#taskPriority').value,
      }),
    });

    $('#taskTitle').value = '';
    $('#taskDesc').value = '';
    $('#taskForm').classList.remove('open');
    loadTasks();
  }

  // ── Notes CRUD ─────────────────────────────────────────────────
  async function loadNotes() {
    try {
      const resp = await fetch('/api/notes');
      const notes = await resp.json();
      const list = $('#noteList');
      list.innerHTML = '';

      if (notes.length === 0) {
        list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dim);font-family:var(--font-ui);font-size:0.8rem;">No notes yet</div>';
        return;
      }

      notes.forEach(n => {
        const card = document.createElement('div');
        card.className = 'panel-card';
        card.innerHTML = `
          <div class="panel-card-header">
            <span class="panel-card-title">${escapeHtml(n.title || 'Untitled')}</span>
            <button class="btn-danger" data-delete-note="${n.id}" title="Delete">✕</button>
          </div>
          <div class="panel-card-body">${escapeHtml(n.content)}</div>
          <div class="panel-card-meta" style="margin-top:6px">${formatDate(n.created_at)}</div>
        `;
        list.appendChild(card);
      });

      // Delete buttons
      list.querySelectorAll('[data-delete-note]').forEach(btn => {
        btn.addEventListener('click', async () => {
          await fetch(`/api/notes/${btn.dataset.deleteNote}`, { method: 'DELETE' });
          loadNotes();
        });
      });

    } catch (e) {
      console.error('Failed to load notes:', e);
    }
  }

  async function submitNote() {
    const content = $('#noteContent').value.trim();
    if (!content) return;

    await fetch('/api/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: $('#noteTitle').value.trim() || 'Untitled Note',
        content,
      }),
    });

    $('#noteTitle').value = '';
    $('#noteContent').value = '';
    $('#noteForm').classList.remove('open');
    loadNotes();
  }

  // ── Knowledge CRUD & Upload ────────────────────────────────────
  function setupUpload() {
    const uploadZone = $('#uploadZone');
    const fileInput = $('#fileInput');

    uploadZone.addEventListener('click', () => fileInput.click());

    uploadZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadZone.classList.add('drag-over');
    });

    uploadZone.addEventListener('dragleave', () => {
      uploadZone.classList.remove('drag-over');
    });

    uploadZone.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadZone.classList.remove('drag-over');
      if (e.dataTransfer.files.length) {
        uploadFile(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) {
        uploadFile(fileInput.files[0]);
        fileInput.value = '';
      }
    });
  }

  async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    const uploadZone = $('#uploadZone');
    const origText = uploadZone.querySelector('.upload-zone-text').textContent;
    uploadZone.querySelector('.upload-zone-text').textContent = 'Uploading...';

    try {
      const resp = await fetch('/api/knowledge/upload', {
        method: 'POST',
        body: formData,
      });
      const data = await resp.json();

      if (data.success) {
        uploadZone.querySelector('.upload-zone-text').textContent = `✓ Uploaded (${data.chunks} chunks)`;
        setTimeout(() => {
          uploadZone.querySelector('.upload-zone-text').textContent = origText;
        }, 2000);
        loadKnowledge();
      } else {
        uploadZone.querySelector('.upload-zone-text').textContent = data.error || 'Upload failed';
        setTimeout(() => {
          uploadZone.querySelector('.upload-zone-text').textContent = origText;
        }, 3000);
      }
    } catch (e) {
      console.error('Upload error:', e);
      uploadZone.querySelector('.upload-zone-text').textContent = 'Upload error';
      setTimeout(() => {
        uploadZone.querySelector('.upload-zone-text').textContent = origText;
      }, 3000);
    }
  }

  async function loadKnowledge() {
    try {
      const resp = await fetch('/api/knowledge');
      const docs = await resp.json();
      const list = $('#knowledgeList');
      list.innerHTML = '';

      if (docs.length === 0) {
        list.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dim);font-family:var(--font-ui);font-size:0.8rem;">No documents uploaded</div>';
        return;
      }

      docs.forEach(d => {
        const div = document.createElement('div');
        div.className = 'knowledge-file';
        const icon = d.file_type === 'pdf' ? '📕' : '📄';
        const size = d.size_bytes > 1024 ? `${(d.size_bytes / 1024).toFixed(1)} KB` : `${d.size_bytes} B`;
        div.innerHTML = `
          <div class="knowledge-file-info">
            <span class="knowledge-file-icon">${icon}</span>
            <div>
              <div class="knowledge-file-name">${escapeHtml(d.name)}</div>
              <div class="knowledge-file-meta">${size} · ${d.chunk_count} chunks</div>
            </div>
          </div>
          <button class="btn-danger" data-delete-doc="${d.id}" title="Delete">✕</button>
        `;
        list.appendChild(div);
      });

      list.querySelectorAll('[data-delete-doc]').forEach(btn => {
        btn.addEventListener('click', async () => {
          await fetch(`/api/knowledge/${btn.dataset.deleteDoc}`, { method: 'DELETE' });
          loadKnowledge();
        });
      });

    } catch (e) {
      console.error('Failed to load knowledge:', e);
    }
  }

  // ── Utilities ──────────────────────────────────────────────────
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function formatMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
    // Lists
    html = html.replace(/^- (.+)$/gm, '• $1');

    return html;
  }

  function formatDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
      return iso;
    }
  }

  // ── Start ──────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);
})();
