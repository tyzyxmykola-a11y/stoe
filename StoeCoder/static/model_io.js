(() => {
  'use strict';

  if (window.__stoeModelIoBooted) return;
  window.__stoeModelIoBooted = true;

  const eventByAction = new Map();
  let ioStatus = null;

  const style = document.createElement('style');
  style.textContent = `
    .model-io-btn { margin-left:8px;padding:2px 7px;border:1px solid #334155;border-radius:4px;background:#0f172a;color:#93c5fd;font:10px 'Space Mono',monospace;cursor:pointer;vertical-align:middle; }
    .model-io-btn:hover { border-color:#60a5fa;color:#dbeafe; }
    .model-io-wrap { margin:5px 0 8px 58px;border:1px solid #263247;border-radius:6px;background:#080d16;overflow:hidden; }
    .model-io-head { padding:6px 9px;font-size:10px;color:#94a3b8;border-bottom:1px solid #1e293b; }
    .model-io-wrap details { border-bottom:1px solid #172033; }
    .model-io-wrap details:last-child { border-bottom:0; }
    .model-io-wrap summary { padding:6px 9px;cursor:pointer;font-size:10px;letter-spacing:.4px;user-select:none; }
    .model-io-wrap summary.trusted { color:#67e8f9; }
    .model-io-wrap summary.model { color:#c4b5fd; }
    .model-io-wrap summary.meta { color:#86efac; }
    .model-io-wrap pre { margin:0;padding:9px;max-height:340px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:10px/1.45 'Space Mono',monospace;color:#cbd5e1;background:#050810; }
    .model-io-error { padding:8px 9px;color:#fca5a5;font-size:10px; }
    .model-io-status { margin-left:6px;font-size:9px;color:#22c55e;letter-spacing:.4px; }
    .model-io-status.error { color:#f87171; }
  `;
  document.head.appendChild(style);

  function setStatus(text, error = false) {
    const title = document.querySelector('#agent-log-panel .log-title');
    if (!title) return;
    if (!ioStatus) {
      ioStatus = document.createElement('span');
      ioStatus.className = 'model-io-status';
      title.appendChild(ioStatus);
    }
    ioStatus.textContent = text;
    ioStatus.classList.toggle('error', !!error);
  }

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
      const response = await fetch('/api/coder/model-io/' + encodeURIComponent(actionId), { credentials:'same-origin', cache:'no-store' });
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
    if (!line || !actionId || line.querySelector('.model-io-btn')) return false;
    line.dataset.modelIoAction = actionId;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'model-io-btn';
    button.textContent = 'Model I/O ▸';
    button.title = 'Show exact local model request and response artifacts';
    button.addEventListener('click', event => {
      event.stopPropagation();
      toggleModelIo(button, actionId, line);
    });
    line.appendChild(button);
    return true;
  }

  function renderedText(event) {
    return event.source + ' · ' + event.message;
  }

  function callNumber(actionId) {
    const match = String(actionId || '').match(/:coder:(\d+)$/);
    return match ? match[1] : null;
  }

  function findLine(lines, event) {
    const exact = renderedText(event);
    for (const line of lines) {
      if (line.dataset.modelIoAction) continue;
      if ((line.textContent || '').includes(exact)) return line;
    }
    const number = callNumber(event?.metadata?.action_id);
    if (!number) return null;
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i];
      if (line.dataset.modelIoAction) continue;
      const text = line.textContent || '';
      if (new RegExp('\\bmodel call\\s+' + number + '\\b').test(text) && text.includes(event.source)) return line;
    }
    return null;
  }

  function scanLog() {
    const body = document.getElementById('agent-log-body');
    if (!body) return 0;
    const lines = Array.from(body.children);
    let attached = 0;
    for (const event of eventByAction.values()) {
      const line = findLine(lines, event);
      if (line && attachButton(line, event.metadata.action_id)) attached += 1;
    }
    return attached;
  }

  async function refreshEvents() {
    try {
      const response = await fetch('/api/coder/events?limit=100', { credentials:'same-origin', cache:'no-store' });
      const events = await response.json();
      if (!response.ok || !Array.isArray(events)) throw new Error('events HTTP ' + response.status);
      for (const event of events) {
        const actionId = event?.metadata?.action_id;
        const eventType = event?.metadata?.event_type;
        if (actionId && ['model_call_complete','model_call_failed'].includes(eventType)) eventByAction.set(actionId, event);
      }
      scanLog();
      setStatus('I/O ready · ' + eventByAction.size);
    } catch (error) {
      setStatus('I/O error', true);
      console.error('SToE Model I/O event refresh failed', error);
    }
  }

  function clearLocalUi() {
    eventByAction.clear();
    document.querySelectorAll('.model-io-wrap').forEach(node => node.remove());
    const original = window.__stoeOriginalClearAgentLog;
    if (typeof original === 'function') original();
    setStatus('I/O ready · 0');
  }

  function installClearHook() {
    if (window.__stoeClearHookInstalled) return;
    if (typeof window.clearAgentLog !== 'function') {
      setTimeout(installClearHook, 100);
      return;
    }
    window.__stoeClearHookInstalled = true;
    window.__stoeOriginalClearAgentLog = window.clearAgentLog;
    window.clearAgentLog = async function() {
      try {
        const response = await fetch('/api/coder/logs/clear', {
          method:'POST',
          credentials:'same-origin',
          cache:'no-store',
          headers:{'Content-Type':'application/json'},
          body:'{}'
        });
        const value = await response.json();
        if (!response.ok || !value.ok) throw new Error(value.error || ('HTTP ' + response.status));
        clearLocalUi();
      } catch (error) {
        setStatus('clear failed', true);
        console.error('SToE log clear failed', error);
      }
    };
  }

  const observer = new MutationObserver(() => scanLog());
  function installObserver() {
    const body = document.getElementById('agent-log-body');
    if (!body) { setTimeout(installObserver, 100); return; }
    observer.observe(body, { childList:true });
    setStatus('I/O loading');
    refreshEvents();
    setInterval(refreshEvents, 1000);
  }

  installClearHook();
  installObserver();
})();
