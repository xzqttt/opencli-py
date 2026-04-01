/**
 * OpenCLI-Py Extension - Background Service Worker
 *
 * Minimal implementation: navigate, exec, cookies
 */

const DAEMON_WS_URL = 'ws://127.0.0.1:19826/ext';
const DAEMON_PING_URL = 'http://127.0.0.1:19826/ping';
const WS_RECONNECT_BASE_DELAY = 2000;
const WS_RECONNECT_MAX_DELAY = 60000;
const WINDOW_IDLE_TIMEOUT = 30000;
const BLANK_PAGE = 'data:text/html,<html></html>';

// State
let ws = null;
let reconnectTimer = null;
let reconnectAttempts = 0;

// Automation sessions: workspace -> { windowId, idleTimer, idleDeadlineAt }
const automationSessions = new Map();

// CDP attached tabs: tabId -> true
const attached = new Set();

// === WebSocket connection ===

async function connect() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;

  // Probe daemon first to avoid console noise
  try {
    const res = await fetch(DAEMON_PING_URL, { signal: AbortSignal.timeout(1000) });
    if (!res.ok) return;
  } catch {
    return;
  }

  try {
    ws = new WebSocket(DAEMON_WS_URL);
  } catch {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log('[opencli-py] Connected to daemon');
    reconnectAttempts = 0;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    ws.send(JSON.stringify({ type: 'hello', version: '0.1.0' }));
  };

  ws.onmessage = async (event) => {
    try {
      const command = JSON.parse(event.data);
      const result = await handleCommand(command);
      ws?.send(JSON.stringify(result));
    } catch (err) {
      console.error('[opencli-py] Message handling error:', err);
    }
  };

  ws.onclose = () => {
    console.log('[opencli-py] Disconnected from daemon');
    ws = null;
    scheduleReconnect();
  };

  ws.onerror = () => {
    ws?.close();
  };
}

const MAX_EAGER_ATTEMPTS = 6;

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectAttempts++;
  if (reconnectAttempts > MAX_EAGER_ATTEMPTS) return;
  const delay = Math.min(WS_RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts - 1), WS_RECONNECT_MAX_DELAY);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

// === Automation window management ===

function getWorkspaceKey(workspace) {
  return workspace?.trim() || 'default';
}

function resetWindowIdleTimer(workspace) {
  const session = automationSessions.get(workspace);
  if (!session) return;
  if (session.idleTimer) clearTimeout(session.idleTimer);
  session.idleDeadlineAt = Date.now() + WINDOW_IDLE_TIMEOUT;
  session.idleTimer = setTimeout(async () => {
    const current = automationSessions.get(workspace);
    if (!current) return;
    try {
      await chrome.windows.remove(current.windowId);
      console.log(`[opencli-py] Automation window ${current.windowId} (${workspace}) closed (idle timeout)`);
    } catch {}
    automationSessions.delete(workspace);
  }, WINDOW_IDLE_TIMEOUT);
}

async function getAutomationWindow(workspace) {
  const existing = automationSessions.get(workspace);
  if (existing) {
    try {
      await chrome.windows.get(existing.windowId);
      return existing.windowId;
    } catch {
      automationSessions.delete(workspace);
    }
  }

  const win = await chrome.windows.create({
    url: BLANK_PAGE,
    focused: false,
    width: 1280,
    height: 900,
    type: 'normal',
  });

  const session = {
    windowId: win.id,
    idleTimer: null,
    idleDeadlineAt: Date.now() + WINDOW_IDLE_TIMEOUT,
  };
  automationSessions.set(workspace, session);
  console.log(`[opencli-py] Created automation window ${session.windowId} (${workspace})`);
  resetWindowIdleTimer(workspace);

  await new Promise(resolve => setTimeout(resolve, 200));
  return session.windowId;
}

// Clean up when window is closed
chrome.windows.onRemoved.addListener((windowId) => {
  for (const [workspace, session] of automationSessions.entries()) {
    if (session.windowId === windowId) {
      console.log(`[opencli-py] Automation window closed (${workspace})`);
      if (session.idleTimer) clearTimeout(session.idleTimer);
      automationSessions.delete(workspace);
    }
  }
});

// === CDP helpers ===

function isDebuggableUrl(url) {
  if (!url) return true;
  return url.startsWith('http://') || url.startsWith('https://') || url === BLANK_PAGE;
}

async function ensureAttached(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (!isDebuggableUrl(tab.url)) {
      attached.delete(tabId);
      throw new Error(`Cannot debug tab ${tabId}: URL is ${tab.url ?? 'unknown'}`);
    }
  } catch (e) {
    if (e instanceof Error && e.message.startsWith('Cannot debug tab')) throw e;
    attached.delete(tabId);
    throw new Error(`Tab ${tabId} no longer exists`);
  }

  if (attached.has(tabId)) {
    try {
      await chrome.debugger.sendCommand({ tabId }, 'Runtime.evaluate', {
        expression: '1', returnByValue: true,
      });
      return;
    } catch {
      attached.delete(tabId);
    }
  }

  try {
    await chrome.debugger.attach({ tabId }, '1.3');
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes('Another debugger is already attached')) {
      try { await chrome.debugger.detach({ tabId }); } catch {}
      try {
        await chrome.debugger.attach({ tabId }, '1.3');
      } catch {
        throw new Error(`attach failed: ${msg}`);
      }
    } else {
      throw new Error(`attach failed: ${msg}`);
    }
  }
  attached.add(tabId);

  try {
    await chrome.debugger.sendCommand({ tabId }, 'Runtime.enable');
  } catch {}
}

async function evaluate(tabId, expression) {
  await ensureAttached(tabId);

  const result = await chrome.debugger.sendCommand({ tabId }, 'Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });

  if (result.exceptionDetails) {
    const errMsg = result.exceptionDetails.exception?.description
      || result.exceptionDetails.text
      || 'Eval error';
    throw new Error(errMsg);
  }

  return result.result?.value;
}

// === Command handlers ===

async function resolveTabId(tabId, workspace) {
  if (tabId !== undefined) {
    try {
      const tab = await chrome.tabs.get(tabId);
      const session = automationSessions.get(workspace);
      if (isDebuggableUrl(tab.url) && session && tab.windowId === session.windowId) {
        return tabId;
      }
    } catch {}
  }

  const windowId = await getAutomationWindow(workspace);
  const tabs = await chrome.tabs.query({ windowId });
  const debuggableTab = tabs.find(t => t.id && isDebuggableUrl(t.url));
  if (debuggableTab?.id) return debuggableTab.id;

  const reuseTab = tabs.find(t => t.id);
  if (reuseTab?.id) {
    await chrome.tabs.update(reuseTab.id, { url: BLANK_PAGE });
    await new Promise(resolve => setTimeout(resolve, 300));
    return reuseTab.id;
  }

  const newTab = await chrome.tabs.create({ windowId, url: BLANK_PAGE, active: true });
  if (!newTab.id) throw new Error('Failed to create tab');
  return newTab.id;
}

async function handleNavigate(cmd) {
  const workspace = getWorkspaceKey(cmd.workspace);
  const tabId = await resolveTabId(cmd.tabId, workspace);
  resetWindowIdleTimer(workspace);

  await chrome.tabs.update(tabId, { url: cmd.url });

  // Wait briefly for navigation to start
  await new Promise(resolve => setTimeout(resolve, 500));

  return { id: cmd.id, ok: true, data: { tabId } };
}

async function handleExec(cmd) {
  const workspace = getWorkspaceKey(cmd.workspace);
  const tabId = await resolveTabId(cmd.tabId, workspace);
  resetWindowIdleTimer(workspace);

  const result = await evaluate(tabId, cmd.code);
  return { id: cmd.id, ok: true, data: result };
}

async function handleCookies(cmd) {
  const details = {};
  if (cmd.domain) details.domain = cmd.domain;
  if (cmd.url) details.url = cmd.url;

  const cookies = await chrome.cookies.getAll(details);
  const data = cookies.map(c => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path,
    secure: c.secure,
    httpOnly: c.httpOnly,
    expirationDate: c.expirationDate,
  }));

  return { id: cmd.id, ok: true, data };
}

async function handleCommand(cmd) {
  const workspace = getWorkspaceKey(cmd.workspace);

  try {
    switch (cmd.action) {
      case 'navigate':
        return await handleNavigate(cmd);
      case 'exec':
        return await handleExec(cmd);
      case 'cookies':
        return await handleCookies(cmd);
      default:
        return { id: cmd.id, ok: false, error: `Unknown action: ${cmd.action}` };
    }
  } catch (err) {
    return {
      id: cmd.id,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

// === Lifecycle ===

let initialized = false;

function initialize() {
  if (initialized) return;
  initialized = true;
  chrome.alarms.create('keepalive', { periodInMinutes: 0.4 });
  connect();
  console.log('[opencli-py] Extension initialized');
}

chrome.runtime.onInstalled.addListener(() => {
  initialize();
});

chrome.runtime.onStartup.addListener(() => {
  initialize();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepalive') connect();
});

// CDP cleanup
chrome.tabs.onRemoved.addListener((tabId) => {
  attached.delete(tabId);
});

chrome.debugger.onDetach.addListener((source) => {
  if (source.tabId) attached.delete(source.tabId);
});

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (info.url && !isDebuggableUrl(info.url)) {
    if (attached.has(tabId)) {
      try { await chrome.debugger.detach({ tabId }); } catch {}
      attached.delete(tabId);
    }
  }
});
