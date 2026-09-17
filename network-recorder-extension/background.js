const PROTOCOL_VERSION = "1.3";
const DEFAULT_STATE = "idle";

let session = {
  state: DEFAULT_STATE,
  tabId: null,
  startedAt: null,
  records: [],
  pending: new Map()
};

function serializeSession() {
  return {
    state: session.state,
    tabId: session.tabId,
    startedAt: session.startedAt,
    count: session.records.length
  };
}

async function publish() {
  const snapshot = serializeSession();
  await chrome.storage.session.set({ recorderSnapshot: snapshot });
  await chrome.runtime.sendMessage({ type: "RECORDER_UPDATED", snapshot }).catch(() => {});
}

function isBusinessRequest(params) {
  if (!params || !["XHR", "Fetch"].includes(params.type)) return false;
  const url = params.request?.url || "";
  const lower = url.toLowerCase();
  if (/\.(?:css|js|map|png|jpe?g|gif|svg|ico|woff2?|ttf|eot|webp|mp4|webm)(?:[?#]|$)/.test(lower)) return false;
  if (/(?:\/health(?:check)?|\/heartbeat|\/ping)(?:[/?#]|$)/.test(lower)) return false;
  return true;
}

function requestKey(tabId, requestId) {
  return `${tabId}:${requestId}`;
}

function toHeaders(headers) {
  return Object.entries(headers || {}).map(([name, value]) => ({ name, value: String(value) }));
}

async function command(tabId, method, params = {}) {
  return chrome.debugger.sendCommand({ tabId }, method, params);
}

async function beginRecording(tabId) {
  if (session.state !== "idle" && session.tabId !== tabId) {
    throw new Error("请先停止正在录制的其他标签页。");
  }
  if (session.state === "paused" && session.tabId === tabId) {
    session.state = "recording";
    await publish();
    return serializeSession();
  }
  if (session.state === "recording") return serializeSession();

  await chrome.debugger.attach({ tabId }, PROTOCOL_VERSION);
  try {
    await command(tabId, "Network.enable", { maxPostDataSize: 10 * 1024 * 1024 });
  } catch (error) {
    await chrome.debugger.detach({ tabId }).catch(() => {});
    throw error;
  }
  session = { state: "recording", tabId, startedAt: new Date().toISOString(), records: [], pending: new Map() };
  await publish();
  return serializeSession();
}

async function stopRecording() {
  const tabId = session.tabId;
  session.state = "idle";
  session.pending.clear();
  session.tabId = null;
  await publish();
  if (Number.isInteger(tabId)) await chrome.debugger.detach({ tabId }).catch(() => {});
  return serializeSession();
}

async function exportRecords() {
  const payload = JSON.stringify(session.records.sort((a, b) => a.timestamp.localeCompare(b.timestamp)), null, 2);
  const dataUrl = `data:application/json;charset=utf-8,${encodeURIComponent(payload)}`;
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  await chrome.downloads.download({ url: dataUrl, filename: `network-recording-${stamp}.json`, saveAs: true });
  return { count: session.records.length };
}

chrome.debugger.onEvent.addListener(async (source, method, params) => {
  if (source.tabId !== session.tabId) return;
  if (method === "Network.requestWillBeSent" && session.state === "recording" && isBusinessRequest(params)) {
    const key = requestKey(source.tabId, params.requestId);
    session.pending.set(key, {
      requestId: params.requestId,
      timestamp: new Date().toISOString(),
      method: params.request.method,
      url: params.request.url,
      request: {
        headers: toHeaders(params.request.headers),
        body: params.request.postData ?? null
      },
      response: null,
      capture: true
    });
    return;
  }

  const key = requestKey(source.tabId, params.requestId);
  const item = session.pending.get(key);
  if (!item) return;

  if (method === "Network.responseReceived") {
    item.response = {
      status: params.response.status,
      statusText: params.response.statusText,
      mimeType: params.response.mimeType,
      headers: toHeaders(params.response.headers),
      body: null,
      bodyEncoding: null
    };
  }

  if (method === "Network.loadingFailed") {
    item.response = item.response || { status: 0, statusText: "", mimeType: "", headers: [], body: null, bodyEncoding: null };
    item.response.error = params.errorText;
    if (item.capture) session.records.push(item);
    session.pending.delete(key);
    await publish();
  }

  if (method === "Network.loadingFinished") {
    if (!item.response) return;
    try {
      const body = await command(source.tabId, "Network.getResponseBody", { requestId: params.requestId });
      item.response.body = body.body;
      item.response.bodyEncoding = body.base64Encoded ? "base64" : "utf-8";
    } catch (error) {
      item.response.bodyError = error.message || String(error);
    }
    if (item.capture) session.records.push(item);
    session.pending.delete(key);
    await publish();
  }
});

chrome.debugger.onDetach.addListener(async (source) => {
  if (source.tabId !== session.tabId) return;
  session.state = "idle";
  session.tabId = null;
  session.pending.clear();
  await publish();
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    switch (message.type) {
      case "GET_STATE": sendResponse({ ok: true, snapshot: serializeSession() }); break;
      case "START": sendResponse({ ok: true, snapshot: await beginRecording(message.tabId) }); break;
      case "PAUSE":
        if (session.state !== "recording") throw new Error("当前不在录制中。");
        session.state = "paused"; await publish(); sendResponse({ ok: true, snapshot: serializeSession() }); break;
      case "RESUME":
        if (session.state !== "paused") throw new Error("当前不在暂停状态。");
        session.state = "recording"; await publish(); sendResponse({ ok: true, snapshot: serializeSession() }); break;
      case "STOP": sendResponse({ ok: true, snapshot: await stopRecording() }); break;
      case "EXPORT": sendResponse({ ok: true, result: await exportRecords() }); break;
      default: throw new Error("未知操作。");
    }
  })().catch(error => sendResponse({ ok: false, error: error.message || String(error) }));
  return true;
});
