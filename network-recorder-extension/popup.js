const labels = { idle: "未开始", recording: "录制中", paused: "已暂停" };
const buttons = Object.fromEntries(["start", "pause", "resume", "stop", "export"].map(id => [id, document.getElementById(id)]));
const stateNode = document.getElementById("state");
const countNode = document.getElementById("count");
const notice = document.getElementById("notice");

function render(snapshot) {
  const state = snapshot.state || "idle";
  stateNode.textContent = labels[state];
  countNode.textContent = snapshot.count || 0;
  buttons.start.disabled = state !== "idle";
  buttons.pause.disabled = state !== "recording";
  buttons.resume.disabled = state !== "paused";
  buttons.stop.disabled = state === "idle";
  buttons.export.disabled = (snapshot.count || 0) === 0;
}

async function send(type, extra = {}) {
  const result = await chrome.runtime.sendMessage({ type, ...extra });
  if (!result?.ok) throw new Error(result?.error || "操作失败");
  return result;
}

async function run(action) {
  try {
    notice.textContent = "正在处理…";
    const result = await action();
    if (result.snapshot) render(result.snapshot);
    notice.textContent = "操作完成。";
  } catch (error) { notice.textContent = error.message; }
}

buttons.start.addEventListener("click", () => run(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !/^https?:/i.test(tab.url || "")) throw new Error("请在普通网页标签中开始录制。");
  return send("START", { tabId: tab.id });
}));
buttons.pause.addEventListener("click", () => run(() => send("PAUSE")));
buttons.resume.addEventListener("click", () => run(() => send("RESUME")));
buttons.stop.addEventListener("click", () => run(() => send("STOP")));
buttons.export.addEventListener("click", () => run(async () => {
  const result = await send("EXPORT");
  notice.textContent = `已导出 ${result.result.count} 条记录。`;
  return result;
}));

chrome.runtime.onMessage.addListener(message => { if (message.type === "RECORDER_UPDATED") render(message.snapshot); });
send("GET_STATE").then(result => render(result.snapshot)).catch(error => { notice.textContent = error.message; });
