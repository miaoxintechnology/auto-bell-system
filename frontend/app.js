/* 自动铃声系统 Web 前端 */
const $ = (id) => document.getElementById(id);
const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

let state = null;
let revision = -1;
let serverOffset = 0;
let selectedScheduleId = "";
let selectedAudioId = "";
let activeTab = "schedule";
let scheduleQuery = "";
let weekdayFilter = "0";
let enabledOnly = false;
let audioQuery = "";
let tempStatusUntil = 0;
let statusTimer = 0;
let refreshing = false;
let confirmResolver = null;
let editingScheduleId = "";
let audioUploadContext = "main";
let lastAddedAudioId = "";
let volumeTimer = 0;
let lastMinuteKey = "";

/* ------------------------------------------------------------------ */
/* 基础工具                                                             */
/* ------------------------------------------------------------------ */
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function basename(path) {
  return String(path || "").split(/[\\/]/).pop() || "";
}

function fmtSize(bytes) {
  let value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  value /= 1024;
  if (value < 1024) return `${value.toFixed(1)} KB`;
  value /= 1024;
  if (value < 1024) return `${value.toFixed(1)} MB`;
  return `${(value / 1024).toFixed(1)} GB`;
}

function weekdayName(iso) {
  if (!iso) return "";
  const day = new Date(iso).getDay();
  return WEEKDAYS[(day + 6) % 7];
}

function setStatus(text, ms = 3000) {
  $("statusLast").textContent = text;
  tempStatusUntil = Date.now() + ms;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => {
    tempStatusUntil = 0;
    showLatestStatus();
  }, ms);
}

function showLatestStatus() {
  if (Date.now() < tempStatusUntil) return;
  if (state && state.logs && state.logs.length) {
    $("statusLast").textContent = `${state.logs[0].time}  ${state.logs[0].text}`;
  } else {
    $("statusLast").textContent = "就绪";
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  let body = null;
  if (contentType.includes("application/json")) {
    body = await response.json();
  } else {
    body = await response.text();
  }
  if (!response.ok) {
    let message = response.statusText;
    if (body && typeof body === "object" && body.detail) {
      message = Array.isArray(body.detail)
        ? body.detail.map((x) => x.msg || JSON.stringify(x)).join("；")
        : body.detail;
    } else if (typeof body === "string" && body) {
      message = body;
    }
    throw new Error(message || `请求失败（${response.status}）`);
  }
  return body;
}

function showError(error) {
  const message = error instanceof Error ? error.message : String(error);
  setStatus(message, 5000);
  $("statusDot").className = "dot error";
  $("statusText").textContent = "操作失败";
}

/* ------------------------------------------------------------------ */
/* 刷新与状态                                                           */
/* ------------------------------------------------------------------ */
async function refresh(force = false) {
  if (refreshing) return;
  refreshing = true;
  try {
    const data = await api("/api/state");
    state = data;
    serverOffset = new Date(data.server_time).getTime() - Date.now();
    const minuteKey = String(data.server_time || "").slice(0, 16);
    if (minuteKey !== lastMinuteKey) {
      lastMinuteKey = minuteKey;
      force = true;
    }
    if (force || data.revision !== revision) {
      revision = data.revision;
      renderAll();
    } else {
      updateDynamicStatus();
      if (!tempStatusUntil) showLatestStatus();
    }
  } catch (error) {
    $("statusDot").className = "dot error";
    $("statusText").textContent = "后端未连接";
    $("statusLast").textContent = "无法连接后端服务，请确认 Python 服务仍在运行。";
  } finally {
    refreshing = false;
  }
}

function renderAll() {
  if (!state) return;
  renderTop();
  renderSchedule();
  renderAudio();
  renderSettings();
  updateDynamicStatus();
  if (!tempStatusUntil) showLatestStatus();
}

function renderTop() {
  $("todaySummary").textContent =
    `今日 ${state.today.count} 条 · 已响 ${state.today.done} · 待响 ${state.today.remaining}`;
  $("statusCount").textContent = `铃声 ${state.schedules.length} 条  |  今日 ${state.today.count} 条`;
  $("statusVolume").textContent = `音量 ${state.settings.volume}%`;
  $("nextText").textContent = state.next
    ? `${state.next.relative} ${state.next.time} · ${state.next.name}`
    : "暂无后续铃声";
  updatePauseButton();
}

function updatePauseButton() {
  const paused = state.settings.paused;
  const icon = paused
    ? '<svg viewBox="0 0 24 24" class="fill"><path d="M8 5.2 19 12 8 18.8z"/></svg>'
    : '<svg viewBox="0 0 24 24" class="fill"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
  $("pauseBtn").innerHTML = `${icon}<span>${paused ? "恢复自动铃声" : "暂停自动铃声"}</span>`;
}

function updateDynamicStatus() {
  if (!state) return;
  const now = new Date(Date.now() + serverOffset);
  $("clock").textContent = now.toLocaleTimeString("zh-CN", { hour12: false });
  const weekday = WEEKDAYS[(now.getDay() + 6) % 7];
  $("dateText").textContent = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${weekday}`;

  const dot = $("statusDot");
  const text = $("statusText");
  if (state.playing) {
    dot.className = "dot playing";
    text.textContent = `正在播放：${state.playing.label}`;
  } else if (state.settings.paused) {
    dot.className = "dot paused";
    text.textContent = "自动铃声已暂停";
  } else {
    dot.className = "dot";
    text.textContent = "自动运行中";
  }
}

/* ------------------------------------------------------------------ */
/* 作息表                                                               */
/* ------------------------------------------------------------------ */
function audioName(audioId) {
  const audio = state.audios.find((item) => item.id === audioId);
  return audio ? audio.name : "音频缺失";
}

function filteredSchedules() {
  const query = scheduleQuery.trim().toLowerCase();
  return state.schedules.filter((schedule) => {
    if (enabledOnly && !schedule.enabled) return false;
    if (weekdayFilter === "-1") {
      const day = new Date(Date.now() + serverOffset).getDay();
      const isoDay = day === 0 ? 7 : day;
      if (!schedule.weekdays.includes(isoDay)) return false;
    } else if (weekdayFilter !== "0" && !schedule.weekdays.includes(Number(weekdayFilter))) {
      return false;
    }
    if (query) {
      const haystack = `${schedule.name} ${schedule.time} ${schedule.weekday_text} ${audioName(schedule.audio_id)}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function statusClass(status) {
  if (status === "播放中") return "status-ok";
  if (status === "已响") return "status-gray";
  if (status === "已停用") return "status-gray";
  return "status-blue";
}

function renderSchedule() {
  const schedules = filteredSchedules();
  const tbody = $("scheduleTable").querySelector("tbody");
  $("scheduleCount").textContent = `显示 ${schedules.length} / 共 ${state.schedules.length} 条`;
  if (!state.schedules.length) {
    $("scheduleTable").hidden = true;
    $("scheduleEmpty").hidden = false;
    $("emptyTitle").textContent = "还没有铃声安排";
    $("emptyDesc").textContent = "新建一条铃声，或先套用一套标准作息作为起点。";
    $("emptyActions").hidden = false;
    updateScheduleActions();
    return;
  }
  if (!schedules.length) {
    $("scheduleTable").hidden = true;
    $("scheduleEmpty").hidden = false;
    $("emptyTitle").textContent = "没有匹配的铃声";
    $("emptyDesc").textContent = "调整搜索条件或星期筛选后再试。";
    $("emptyActions").hidden = true;
    updateScheduleActions();
    return;
  }
  $("scheduleEmpty").hidden = true;
  $("scheduleTable").hidden = false;
  if (!schedules.some((s) => s.id === selectedScheduleId)) selectedScheduleId = "";
  tbody.innerHTML = schedules.map((schedule) => {
    const nextClass = state.next && state.next.schedule_id === schedule.id ? "next-row" : "";
    const selected = schedule.id === selectedScheduleId ? "selected" : "";
    return `<tr data-id="${escapeHtml(schedule.id)}" class="${nextClass} ${selected}">
      <td><span class="time-cell">${escapeHtml(schedule.time)}</span></td>
      <td title="${escapeHtml(schedule.name)}">${escapeHtml(schedule.name)}</td>
      <td><span class="weekday-chip">${escapeHtml(schedule.weekday_text)}</span></td>
      <td title="${escapeHtml(audioName(schedule.audio_id))}"><span class="audio-icon">♪</span>${escapeHtml(audioName(schedule.audio_id))}</td>
      <td class="center">${escapeHtml(schedule.next_text || "—")}</td>
      <td class="center ${statusClass(schedule.status)}">${escapeHtml(schedule.status)}</td>
      <td class="center"><label class="checkbox-cell"><input type="checkbox" data-enable="${escapeHtml(schedule.id)}" ${schedule.enabled ? "checked" : ""}></label></td>
    </tr>`;
  }).join("");
  updateScheduleActions();
}

function updateScheduleActions() {
  const has = Boolean(selectedScheduleId);
  $("previewScheduleBtn").disabled = !has;
  $("editScheduleBtn").disabled = !has;
  $("deleteScheduleBtn").disabled = !has;
}

function selectSchedule(id) {
  selectedScheduleId = id;
  document.querySelectorAll("#scheduleTable tbody tr").forEach((row) => {
    row.classList.toggle("selected", row.dataset.id === id);
  });
  updateScheduleActions();
}

function scheduleModalOpen(mode, schedule = null) {
  if (!state.audios.length) {
    showError("音频库为空，请先导入音频");
    return;
  }
  editingScheduleId = schedule ? schedule.id : "";
  $("scheduleModalTitle").textContent = schedule ? "编辑铃声时间与播放设置" : "添加一条铃声";
  $("scheduleError").hidden = true;
  $("scheduleError").textContent = "";
  $("scheduleName").value = schedule ? schedule.name : "上课铃";
  $("scheduleEnabled").checked = schedule ? schedule.enabled : true;
  $("dayChecks").querySelectorAll("input").forEach((box) => {
    box.checked = schedule ? schedule.weekdays.includes(Number(box.value)) : Number(box.value) <= 5;
  });
  populateModalAudio(schedule ? schedule.audio_id : "");
  if (schedule) {
    const [hour, minute] = schedule.time.split(":").map(Number);
    $("hourSelect").value = String(hour).padStart(2, "0");
    $("minuteSelect").value = String(minute).padStart(2, "0");
  } else {
    const moment = new Date(Date.now() + serverOffset + 10 * 60 * 1000);
    let hour = moment.getHours();
    let minute = Math.ceil(moment.getMinutes() / 5) * 5;
    if (minute >= 60) {
      minute = 0;
      hour = (hour + 1) % 24;
    }
    $("hourSelect").value = String(hour).padStart(2, "0");
    $("minuteSelect").value = String(minute).padStart(2, "0");
    $("scheduleName").select();
  }
  openModal("scheduleModal");
}

function populateModalAudio(preferred = "") {
  const select = $("scheduleAudio");
  select.innerHTML = state.audios.map((audio) =>
    `<option value="${escapeHtml(audio.id)}">${escapeHtml(audio.name)}${audio.builtin ? "（内置）" : ""}</option>`
  ).join("");
  const wanted = preferred || lastAddedAudioId || (state.audios[0] && state.audios[0].id) || "";
  if (wanted) select.value = wanted;
  $("previewModalAudio").disabled = !select.value;
}

async function submitSchedule(event) {
  event.preventDefault();
  const error = $("scheduleError");
  error.hidden = true;
  const name = $("scheduleName").value.trim();
  const audioId = $("scheduleAudio").value;
  const days = [...$("dayChecks").querySelectorAll("input:checked")].map((box) => Number(box.value));
  if (!name) {
    error.textContent = "请填写铃声名称。";
    error.hidden = false;
    return;
  }
  if (!days.length) {
    error.textContent = "请至少选择一个响铃星期。";
    error.hidden = false;
    return;
  }
  if (!audioId) {
    error.textContent = "请选择播放音频。";
    error.hidden = false;
    return;
  }
  const payload = {
    time: `${$("hourSelect").value}:${$("minuteSelect").value}`,
    name,
    audio_id: audioId,
    weekdays: days,
    enabled: $("scheduleEnabled").checked,
  };
  try {
    const result = editingScheduleId
      ? await api(`/api/schedules/${encodeURIComponent(editingScheduleId)}`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        })
      : await api("/api/schedules", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
    selectedScheduleId = result.schedule.id;
    closeModal("scheduleModal");
    await refresh(true);
    setStatus(editingScheduleId ? "铃声设置已保存" : `已添加 ${payload.time} · ${name}`, 3000);
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  }
}

/* ------------------------------------------------------------------ */
/* 音频库                                                               */
/* ------------------------------------------------------------------ */
function filteredAudios() {
  const query = audioQuery.trim().toLowerCase();
  return state.audios.filter((audio) => {
    if (!query) return true;
    return `${audio.name} ${audio.filename} ${audio.source_name}`.toLowerCase().includes(query);
  });
}

function renderAudio() {
  const audios = filteredAudios();
  const tbody = $("audioTable").querySelector("tbody");
  $("audioCount").textContent = `${state.audios.length} 个音频 · ${fmtSize(state.audios.reduce((sum, a) => sum + (a.size || 0), 0))}`;
  if (!audios.length) {
    $("audioTable").hidden = true;
    $("audioEmpty").hidden = false;
    $("audioEmpty").querySelector("strong").textContent =
      state.audios.length ? "没有匹配的音频" : "音频库还是空的";
    updateAudioActions();
    return;
  }
  $("audioTable").hidden = false;
  $("audioEmpty").hidden = true;
  if (!audios.some((a) => a.id === selectedAudioId)) selectedAudioId = "";
  tbody.innerHTML = audios.map((audio) => {
    const selected = audio.id === selectedAudioId ? "selected" : "";
    const source = audio.builtin ? "程序内置" : basename(audio.source_name) || audio.filename;
    const status = audio.exists ? "正常" : "缺失";
    return `<tr data-id="${escapeHtml(audio.id)}" class="${selected}">
      <td title="${escapeHtml(audio.name)}">${escapeHtml(audio.name)}</td>
      <td class="center">${escapeHtml((audio.filename.split(".").pop() || "—").toUpperCase())}</td>
      <td class="center">${escapeHtml(fmtSize(audio.size))}</td>
      <td class="center">${audio.usage ? `${audio.usage} 条` : "—"}</td>
      <td class="center">${audio.builtin ? "内置" : "导入"}</td>
      <td title="${escapeHtml(audio.source_name || audio.filename)}">${escapeHtml(source)}</td>
      <td class="center ${audio.exists ? "" : "status-red"}">${status}</td>
    </tr>`;
  }).join("");
  updateAudioActions();
}

function updateAudioActions() {
  const audio = state.audios.find((a) => a.id === selectedAudioId);
  $("previewAudioBtn").disabled = !audio;
  $("deleteAudioBtn").disabled = !audio || audio.builtin;
}

function selectAudio(id) {
  selectedAudioId = id;
  document.querySelectorAll("#audioTable tbody tr").forEach((row) => {
    row.classList.toggle("selected", row.dataset.id === id);
  });
  updateAudioActions();
}

async function uploadAudioFiles(fileList, context = "main") {
  if (!fileList || !fileList.length) return;
  const form = new FormData();
  for (const file of fileList) form.append("files", file);
  try {
    setStatus("正在上传音频…", 60000);
    const result = await api("/api/audios", { method: "POST", body: form });
    if (result.added && result.added.length) {
      lastAddedAudioId = result.added[result.added.length - 1].id;
      selectedAudioId = lastAddedAudioId;
    }
    await refresh(true);
    if (context === "modal" && !$("scheduleModal").hidden) {
      populateModalAudio(lastAddedAudioId);
    }
    setStatus(result.errors && result.errors.length
      ? `已导入 ${result.added.length} 个，${result.errors.length} 个失败`
      : `已导入 ${result.added.length} 个音频文件`, 3200);
  } catch (error) {
    showError(error);
  }
}

/* ------------------------------------------------------------------ */
/* 设置                                                                 */
/* ------------------------------------------------------------------ */
function renderSettings() {
  $("configPath").value = state.config_path || "";
  $("dataPath").value = state.data_dir || "";
  $("serverUrl").textContent = location.origin;
  $("volumeValue").textContent = `${state.settings.volume}%`;
  if (document.activeElement !== $("volumeSlider")) {
    $("volumeSlider").value = state.settings.volume;
  }
  const logs = (state.logs || []).slice(0, 10)
    .map((line) => `[${line.time}] ${line.text}`)
    .join("\n");
  $("logView").textContent = logs || "暂无运行日志。";
  $("logCount").textContent = `显示最近 ${(state.logs || []).length} 条`;
}

async function setPaused() {
  try {
    await api("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paused: !state.settings.paused }),
    });
    await refresh(true);
    setStatus(state.settings.paused ? "自动铃声已暂停" : "自动铃声已恢复");
  } catch (error) {
    showError(error);
  }
}

async function updateVolume(value) {
  $("volumeValue").textContent = `${value}%`;
  clearTimeout(volumeTimer);
  volumeTimer = setTimeout(async () => {
    try {
      await api("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ volume: Number(value) }),
      });
      await refresh(true);
    } catch (error) {
      showError(error);
    }
  }, 250);
}

/* ------------------------------------------------------------------ */
/* 配置 / 数据转移                                                       */
/* ------------------------------------------------------------------ */
async function openConfigEditor() {
  try {
    const result = await api("/api/config");
    $("configEditor").value = result.content;
    $("configError").hidden = true;
    openModal("configModal");
  } catch (error) {
    showError(error);
  }
}

async function saveConfig() {
  $("configError").hidden = true;
  try {
    await api("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: $("configEditor").value }),
    });
    closeModal("configModal");
    await refresh(true);
    setStatus("配置文件已保存并重新加载");
  } catch (error) {
    $("configError").textContent = error.message;
    $("configError").hidden = false;
  }
}

async function reloadConfig() {
  try {
    await api("/api/config/reload", { method: "POST" });
    await refresh(true);
    setStatus("配置文件已重新加载");
  } catch (error) {
    showError(error);
  }
}

async function importData(file) {
  if (!file) return;
  const confirmed = await openConfirm("导入数据包", "导入会替换当前全部作息、音频库和设置。导入前会自动备份当前数据，确定继续吗？", "导入", true);
  if (!confirmed) {
    $("importFileInput").value = "";
    return;
  }
  const form = new FormData();
  form.append("file", file);
  try {
    setStatus("正在导入数据包…", 60000);
    const result = await api("/api/import", { method: "POST", body: form });
    await refresh(true);
    setStatus("导入完成，原数据已自动备份", 4200);
    if (result.backup) console.info("backup:", result.backup);
  } catch (error) {
    showError(error);
  } finally {
    $("importFileInput").value = "";
  }
}

/* ------------------------------------------------------------------ */
/* 模态框 / 确认框                                                       */
/* ------------------------------------------------------------------ */
function openModal(id) {
  $(id).hidden = false;
  document.body.classList.add("modal-open");
}

function closeModal(id) {
  $(id).hidden = true;
  if ([...document.querySelectorAll(".modal")].every((m) => m.hidden)) {
    document.body.classList.remove("modal-open");
  }
}

function openConfirm(title, message, confirmText = "确定", danger = true) {
  $("confirmTitle").textContent = title;
  $("confirmMessage").textContent = message;
  $("confirmOk").textContent = confirmText;
  $("confirmOk").className = `btn ${danger ? "danger" : "primary"}`;
  openModal("confirmModal");
  return new Promise((resolve) => { confirmResolver = resolve; });
}

function resolveConfirm(value) {
  closeModal("confirmModal");
  if (confirmResolver) {
    const resolver = confirmResolver;
    confirmResolver = null;
    resolver(value);
  }
}

/* ------------------------------------------------------------------ */
/* 操作                                                                 */
/* ------------------------------------------------------------------ */
async function deleteSchedule() {
  const schedule = state.schedules.find((s) => s.id === selectedScheduleId);
  if (!schedule) return;
  if (!await openConfirm("删除铃声", `${schedule.time} · ${schedule.name} 将从作息中移除，此操作不可撤销。`, "删除", true)) return;
  try {
    await api(`/api/schedules/${encodeURIComponent(schedule.id)}`, { method: "DELETE" });
    selectedScheduleId = "";
    await refresh(true);
    setStatus("铃声已删除");
  } catch (error) {
    showError(error);
  }
}

async function clearSchedules() {
  if (!state.schedules.length) return;
  if (!await openConfirm("清空全部铃声", "将删除当前全部铃声安排，音频文件不会被删除。此操作不可撤销。", "清空全部", true)) return;
  try {
    await api("/api/schedules", { method: "DELETE" });
    selectedScheduleId = "";
    await refresh(true);
    setStatus("铃声计划已清空");
  } catch (error) {
    showError(error);
  }
}

async function applyTemplate() {
  if (state.schedules.length) {
    if (!await openConfirm("套用示例作息", "将用一套标准作息替换当前铃声安排，音频文件不会受影响。", "替换", true)) return;
  }
  try {
    const result = await api("/api/schedules/template", { method: "POST" });
    selectedScheduleId = "";
    await refresh(true);
    setStatus(`已套用 ${result.count} 条示例作息`);
  } catch (error) {
    showError(error);
  }
}

async function deleteAudio() {
  const audio = state.audios.find((a) => a.id === selectedAudioId);
  if (!audio) return;
  if (!await openConfirm("删除音频文件", `将从音频库删除「${audio.name}」，文件会从数据目录移除。`, "删除", true)) return;
  try {
    await api(`/api/audios/${encodeURIComponent(audio.id)}`, { method: "DELETE" });
    selectedAudioId = "";
    await refresh(true);
    setStatus("音频已删除");
  } catch (error) {
    showError(error);
  }
}

async function previewSelectedAudio() {
  if (!selectedAudioId) return;
  try {
    await api(`/api/audios/${encodeURIComponent(selectedAudioId)}/preview`, { method: "POST" });
    await refresh(true);
  } catch (error) {
    showError(error);
  }
}

/* ------------------------------------------------------------------ */
/* 事件绑定                                                             */
/* ------------------------------------------------------------------ */
function bindEvents() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tab;
      document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === button));
      document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${activeTab}`));
      if (location.hash !== `#${activeTab}`) history.replaceState(null, "", `#${activeTab}`);
    });
  });

  $("newScheduleBtn").addEventListener("click", () => scheduleModalOpen("create"));
  $("emptyNewBtn").addEventListener("click", () => scheduleModalOpen("create"));
  $("emptyTemplateBtn").addEventListener("click", applyTemplate);
  $("importAudioBtn").addEventListener("click", () => { audioUploadContext = "main"; $("audioFileInput").click(); });
  $("audioImportBtn").addEventListener("click", () => { audioUploadContext = "main"; $("audioFileInput").click(); });
  $("emptyAudioBtn").addEventListener("click", () => { audioUploadContext = "main"; $("audioFileInput").click(); });
  $("importModalAudio").addEventListener("click", () => { audioUploadContext = "modal"; $("audioFileInput").click(); });
  $("audioFileInput").addEventListener("change", async () => {
    const files = $("audioFileInput").files;
    await uploadAudioFiles(files, audioUploadContext);
    $("audioFileInput").value = "";
  });

  $("pauseBtn").addEventListener("click", setPaused);
  $("moreBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    $("moreMenu").hidden = !$("moreMenu").hidden;
  });
  $("moreMenu").addEventListener("click", async (event) => {
    const action = event.target.dataset.action;
    $("moreMenu").hidden = true;
    if (action === "template") await applyTemplate();
    if (action === "clear") await clearSchedules();
  });
  document.addEventListener("click", () => { $("moreMenu").hidden = true; });

  $("scheduleSearch").addEventListener("input", (event) => { scheduleQuery = event.target.value; renderSchedule(); });
  $("weekdayFilter").addEventListener("change", (event) => { weekdayFilter = event.target.value; renderSchedule(); });
  $("enabledOnly").addEventListener("change", (event) => { enabledOnly = event.target.checked; renderSchedule(); });
  $("audioSearch").addEventListener("input", (event) => { audioQuery = event.target.value; renderAudio(); });

  $("scheduleTable").addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-id]");
    if (!row) return;
    if (event.target.matches("input[type=checkbox]")) return;
    selectSchedule(row.dataset.id);
  });
  $("scheduleTable").addEventListener("dblclick", (event) => {
    const row = event.target.closest("tr[data-id]");
    if (!row || event.target.matches("input[type=checkbox]")) return;
    const schedule = state.schedules.find((s) => s.id === row.dataset.id);
    if (schedule) scheduleModalOpen("edit", schedule);
  });
  $("scheduleTable").addEventListener("change", async (event) => {
    if (!event.target.matches("input[data-enable]")) return;
    const id = event.target.dataset.enable;
    try {
      await api(`/api/schedules/${encodeURIComponent(id)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: event.target.checked }),
      });
      await refresh(true);
    } catch (error) {
      showError(error);
      event.target.checked = !event.target.checked;
    }
  });
  $("previewScheduleBtn").addEventListener("click", async () => {
    if (!selectedScheduleId) return;
    try {
      await api(`/api/schedules/${encodeURIComponent(selectedScheduleId)}/preview`, { method: "POST" });
      await refresh(true);
    } catch (error) { showError(error); }
  });
  $("editScheduleBtn").addEventListener("click", () => {
    const schedule = state.schedules.find((s) => s.id === selectedScheduleId);
    if (schedule) scheduleModalOpen("edit", schedule);
  });
  $("deleteScheduleBtn").addEventListener("click", deleteSchedule);

  $("audioTable").addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-id]");
    if (row) selectAudio(row.dataset.id);
  });
  $("audioTable").addEventListener("dblclick", (event) => {
    const row = event.target.closest("tr[data-id]");
    if (!row) return;
    selectAudio(row.dataset.id);
    previewSelectedAudio();
  });
  $("previewAudioBtn").addEventListener("click", previewSelectedAudio);
  $("deleteAudioBtn").addEventListener("click", deleteAudio);

  const dropZone = $("audioDropZone");
  ["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add("drag-over");
  }));
  ["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove("drag-over");
  }));
  dropZone.addEventListener("drop", (event) => {
    if (event.dataTransfer && event.dataTransfer.files) {
      uploadAudioFiles(event.dataTransfer.files, "main");
    }
  });

  $("volumeSlider").addEventListener("input", (event) => updateVolume(event.target.value));
  $("testSoundBtn").addEventListener("click", async () => {
    const audio = state.audios.find((a) => a.id === "builtin-up") || state.audios[0];
    if (!audio) return;
    try {
      await api(`/api/audios/${encodeURIComponent(audio.id)}/preview`, { method: "POST" });
      await refresh(true);
    } catch (error) { showError(error); }
  });

  $("editConfigBtn").addEventListener("click", openConfigEditor);
  $("saveConfigBtn").addEventListener("click", saveConfig);
  $("reloadConfigBtn").addEventListener("click", reloadConfig);
  $("exportDataBtn").addEventListener("click", () => { window.location.href = "/api/export"; });
  $("importDataBtn").addEventListener("click", () => $("importFileInput").click());
  $("importFileInput").addEventListener("change", () => importData($("importFileInput").files[0]));

  $("scheduleForm").addEventListener("submit", submitSchedule);
  $("previewModalAudio").addEventListener("click", async () => {
    const id = $("scheduleAudio").value;
    if (!id) return;
    try {
      await api(`/api/audios/${encodeURIComponent(id)}/preview`, { method: "POST" });
      await refresh(true);
    } catch (error) { showError(error); }
  });

  $("dayChecks").querySelectorAll("input").forEach((box) => {
    box.addEventListener("change", () => { /* 保留原生复选框行为 */ });
  });
  document.querySelectorAll("[data-days]").forEach((button) => {
    button.addEventListener("click", () => {
      const days = button.dataset.days ? button.dataset.days.split(",").map(Number) : [];
      $("dayChecks").querySelectorAll("input").forEach((box) => {
        box.checked = days.includes(Number(box.value));
      });
    });
  });

  $("confirmCancel").addEventListener("click", () => resolveConfirm(false));
  $("confirmOk").addEventListener("click", () => resolveConfirm(true));
  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => closeModal(button.dataset.close));
  });
  document.querySelectorAll(".modal").forEach((modal) => {
    modal.addEventListener("click", (event) => {
      if (event.target === modal && modal.id !== "confirmModal") closeModal(modal.id);
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const open = [...document.querySelectorAll(".modal")].find((m) => !m.hidden);
      if (open && open.id !== "confirmModal") closeModal(open.id);
    }
  });
}

/* ------------------------------------------------------------------ */
/* Electron 无边框窗口                                                  */
/* ------------------------------------------------------------------ */
function initDesktopWindow() {
  if (!window.desktop) return;
  document.body.classList.add("electron");
  const setMaximized = (maximized) => {
    document.body.classList.toggle("maximized", Boolean(maximized));
    $("winMax").title = maximized ? "还原" : "最大化";
    $("winMax").setAttribute("aria-label", maximized ? "还原" : "最大化");
    $("winMax").innerHTML = maximized
      ? '<svg viewBox="0 0 24 24"><rect x="7" y="5" width="12" height="12" rx="1"/><path d="M5 9v10h10"/></svg>'
      : '<svg viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="1"/></svg>';
  };
  $("winMin").addEventListener("click", () => window.desktop.minimize());
  $("winMax").addEventListener("click", () => window.desktop.toggleMaximize());
  $("winClose").addEventListener("click", () => window.desktop.close());
  window.desktop.onMaximized((maximized) => setMaximized(maximized));
  document.querySelector(".topbar").addEventListener("dblclick", (event) => {
    if (!event.target.closest("button")) window.desktop.toggleMaximize();
  });
  window.desktop.isMaximized().then(setMaximized);
}

/* ------------------------------------------------------------------ */
/* 初始化                                                               */
/* ------------------------------------------------------------------ */
function init() {
  // 时间选择器
  const hour = $("hourSelect"), minute = $("minuteSelect");
  for (let i = 0; i < 24; i += 1) {
    const option = document.createElement("option");
    option.value = String(i).padStart(2, "0");
    option.textContent = String(i).padStart(2, "0");
    hour.appendChild(option);
  }
  for (let i = 0; i < 60; i += 1) {
    const option = document.createElement("option");
    option.value = String(i).padStart(2, "0");
    option.textContent = String(i).padStart(2, "0");
    minute.appendChild(option);
  }
  // 星期
  WEEKDAYS.forEach((name, index) => {
    const label = document.createElement("label");
    label.className = "check";
    label.innerHTML = `<input type="checkbox" value="${index + 1}"> ${name}`;
    $("dayChecks").appendChild(label);
  });
  bindEvents();
  initDesktopWindow();
  const hash = location.hash.replace("#", "");
  if (["schedule", "audio", "settings"].includes(hash)) {
    document.querySelector(`.tab[data-tab="${hash}"]`).click();
  }
  refresh(true);
  setInterval(refresh, 1000);
  setInterval(updateDynamicStatus, 250);
}

document.addEventListener("DOMContentLoaded", init);
