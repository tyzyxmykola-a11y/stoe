(() => {
  'use strict';

  const eventByAction = new Map();

  const style = document.createElement('style');
  style.textContent = `
    .model-io-btn {
      margin-left: 8px; padding: 2px 7px; border: 1px solid #334155; border-radius: 4px;
      background: #0f172a; color: #93c5fd; font: 10px 'Space Mono', monospace; cursor: pointer;
      vertical-align: middle;
    }
    .model-io-btn:hover { border-color: #60a5fa; color: #dbeafe; }
    .model-io-wrap { margin: 5px 0 8px 58px; border: 1px solid #263247; border-radius: 6px; background: #080d16; overflow: hidden; }
    .model-io-head { padding: 6px 9px; font-size: 10px; color: #94a3b8; border-bottom: 1px solid #1e293b; }
    .model-io-wrap details { border-bottom: 1px solid #172033; }
    .model-io-wrap details:last-child { border-bottom: 0; }
    .model-io-wrap summary { padding: 6px 9px; cursor: pointer; font-size: 10px; letter-spacing: .4px; user-select: none; }
    .model-io-wrap summary.trusted { color: #67e8f9; }
    .model-io-wrap summary.model { color: #c4b5fd; }
    .model-io-wrap summary.meta { color: #86efac; }
    .model-io-wrap pre {
      margin: 0; padding: 9px; max-height: 340px; overflow: auto; white-space: pre-wrap; word-break: break-word;
      font: 10px/1.45 'Space Mono', monospace; color: #cbd5e1; background: #050810;
    }
    .model-io-error { padding: 8px 9px; color: #fca5a5; font-size: 10px; }
  `;
  document.head.appendChild(style);

  function pretty(value) {
    if (value === null || value === undefined) return '(not available)';
    try { return JSON.stringify(value, null, 2); }
    catch (_) { return String(value); }
  }

  function parsedPrompt(snapshot) {
    const prompt = snapshot?.request?.payload?.prompt;
    if (typeof prompt !== 'string') return null;
    try { return JSON.parse(prompt); }
    catch (_) { return prompt; }
  }

  function makeDetails(label, value, kind, open = false) {
    const details = document.createElement('details');
    if (open) details.open = true;
    const summary = document.createElement('summary');
    summary.className = kind;
    summary.textContent = label;
    const pre = document.createElement('pre');
    pre.textContent = pretty(value);
    details.append(summary, pre);
    return details;
  }

  function buildPanel(snapshot) {
    const wrap = document.createElement('div');
    wrap.className = 'model-io-wrap';
    wrap.dataset.actionId = snapshot.action_id;

    const head = document.createElement('div');
    head.className = 'model-io-head';
    head.textContent = snapshot.action_id;
    wrap.appendChild(head);

    wrap.appendChild(makeDetails('TRUSTED REQUEST ENVELOPE', snapshot.request, 'trusted'));
    const prompt = parsedPrompt(snapshot);
    if (prompt !== null) wrap.appendChild(makeDetails('MODEL-VISIBLE PROMPT', prompt, 'trusted'));
    wrap.appendChild(makeDetails('MODEL RAW RESPONSE', snapshot.raw_response, 'model', true));
    wrap.appendChild(makeDetails('PARSED / ACCEPTED RESPONSE', snapshot.parsed_response, 'model'));
    wrap.appendChild(makeDetails('METRICS', snapshot.metrics, 'meta'));
    if (snapshot.error) wrap.appendChild(makeDetails('CAPTURED ERROR', snapshot.error, 'model', true));
    return wrap;
  }

  async function toggleModelIo(button, actionId, line) {
    const next = line.nextElementSibling;
    if (next && next.classList.contains('model-io-wrap') && next.dataset.actionId === actionId) {
      const hidden = next.style.display === 'none';
      next.style.display = hidden ? '' : 'none';
      button.textContent = hidden ? 'Model I/O ▾' : 'Model I/O ▸';
      return;
    }

    button.disabled = true;
    button.textContent = 'Model I/O …';
    try {
      const response = await fetch('/api/coder/model-io/' + encodeURIComponent(actionId), { credentials: 'same-origin' });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || ('HTTP ' + response.status));
      line.insertAdjacentElement('afterend', buildPanel(value));
      button.textContent = 'Model I/O ▾';
    } catch (error) {
      const panel = document.createElement('div');
      panel.className = 'model-io-wrap';
      panel.dataset.actionId = actionId;
      const message = document.createElement('div');
      message.className = 'model-io-error';
      message.textContent = 'Model I/O unavailable: ' + error.message;
      panel.appendChild(message);
      line.insertAdjacentElement('afterend', panel);
      button.textContent = 'Model I/O ▾';
    } finally {
      button.disabled = false;
    }
  }

  function attachButton(line, actionId) {
    if (!line || !actionId || line.querySelector('.model-io-btn')) return;
    line.dataset.modelIoAction = actionId;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'model-io-btn';
    button.textContent = 'Model I/O ▸';
    button.title = 'Show exact local model request and response artifacts';
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      toggleModelIo(button, actionId, line);
    });
    line.appendChild(button);
  }

  function renderedText(event) {
    return (event?.metadata?.event_type === 'task_finished' ? '★ ' : '') + event.source + ' · ' + event.message;
  }

  function scanLog() {
    const body = document.getElementById('agent-log-body');
    if (!body) return;
    const lines = Array.from(body.children);
    for (const event of eventByAction.values()) {
      const expected = renderedText(event);
      for (const line of lines) {
        if (line.dataset.modelIoAction) continue;
        const text = line.textContent || '';
        if (text.includes(expected)) {
          attachButton(line, event.metadata.action_id);
          break;
        }
      }
    }
  }

  async function refreshEvents() {
    try {
      const response = await fetch('/api/coder/events?limit=200', { credentials: 'same-origin' });
      const events = await response.json();
      if (!response.ok || !Array.isArray(events)) return;
      for (const event of events) {
        const actionId = event?.metadata?.action_id;
        const eventType = event?.metadata?.event_type;
        if (actionId && ['model_call_complete', 'model_call_failed'].includes(eventType)) {
          eventByAction.set(actionId, event);
        }
      }
      scanLog();
    } catch (_) {
      // Model I/O UI is diagnostic-only and must never disturb the main UI.
    }
  }

  const observer = new MutationObserver(() => scanLog());
  function installObserver() {
    const body = document.getElementById('agent-log-body');
    if (!body) {
      setTimeout(installObserver, 100);
      return;
    }
    observer.observe(body, { childList: true });
    refreshEvents();
    setInterval(refreshEvents, 1000);
  }

  installObserver();
})();
