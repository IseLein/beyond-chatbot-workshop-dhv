const monthLabel = document.getElementById("month-label");
const calendarGrid = document.getElementById("calendar-grid");
const selectedDateLabel = document.getElementById("selected-date-label");
const eventsList = document.getElementById("events-list");
const addEventForm = document.getElementById("add-event-form");
const eventTitleInput = document.getElementById("event-title");
const eventTimeInput = document.getElementById("event-time");
const prevMonthBtn = document.getElementById("prev-month");
const nextMonthBtn = document.getElementById("next-month");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatLog = document.getElementById("chat-log");
const chatSend = document.getElementById("chat-send");
const chatStatus = document.getElementById("chat-status");
const chatStatusText = document.getElementById("chat-status-text");

const today = new Date();
let currentMonth = new Date(today.getFullYear(), today.getMonth(), 1);
let selectedDate = toDateKey(today);
let allEvents = [];
let chatHistory = [
  {
    role: "assistant",
    content: "Hi, I can list, add, and remove events. Try: 'Add demo prep on 2026-03-02 at 14:00'.",
  },
];
let isChatWaiting = false;

function toDateKey(d) {
  const year = d.getFullYear();
  const month = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseDateKey(key) {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function monthTitle(d) {
  return d.toLocaleString(undefined, { month: "long", year: "numeric" });
}

function formatToolCall(toolCall) {
  const name = toolCall?.name || "unknown_tool";
  let argsText = "{}";
  try {
    argsText = JSON.stringify(toolCall?.arguments ?? {});
  } catch (_err) {
    argsText = "{}";
  }
  const clipped = argsText.length > 180 ? `${argsText.slice(0, 177)}...` : argsText;
  return `${name}(${clipped})`;
}

function setChatWaiting(waiting) {
  isChatWaiting = waiting;
  chatStatus.classList.toggle("busy", waiting);
  chatStatus.classList.toggle("idle", !waiting);
  chatStatusText.textContent = waiting ? "Assistant is working..." : "Ready";

  chatSend.disabled = waiting;
  chatInput.disabled = waiting;
  chatSend.textContent = waiting ? "Working..." : "Send";
}

function renderChat() {
  chatLog.innerHTML = "";
  chatHistory.forEach((msg) => {
    const div = document.createElement("div");
    if (msg.role === "tool_call") {
      div.className = "msg tool-call";
      div.textContent = `[tool_call] ${msg.content}`;
    } else {
      div.className = `msg ${msg.role}`;
      div.textContent = msg.content;
    }
    chatLog.appendChild(div);
  });

  if (isChatWaiting) {
    const pending = document.createElement("div");
    pending.className = "msg assistant pending";
    pending.textContent = "Thinking";
    const dots = document.createElement("span");
    dots.className = "typing-dots";
    dots.textContent = "...";
    pending.appendChild(dots);
    chatLog.appendChild(pending);
  }

  chatLog.scrollTop = chatLog.scrollHeight;
}

function eventMapByDate(events) {
  const map = new Map();
  events.forEach((evt) => {
    const key = evt.date;
    map.set(key, (map.get(key) || 0) + 1);
  });
  return map;
}

function renderCalendar() {
  monthLabel.textContent = monthTitle(currentMonth);
  calendarGrid.innerHTML = "";

  const year = currentMonth.getFullYear();
  const month = currentMonth.getMonth();
  const firstDay = new Date(year, month, 1);
  const startWeekday = firstDay.getDay();
  const lastDate = new Date(year, month + 1, 0).getDate();
  const counts = eventMapByDate(allEvents);

  for (let i = 0; i < startWeekday; i += 1) {
    const empty = document.createElement("div");
    empty.className = "day-cell empty";
    calendarGrid.appendChild(empty);
  }

  for (let day = 1; day <= lastDate; day += 1) {
    const key = toDateKey(new Date(year, month, day));
    const button = document.createElement("button");
    button.type = "button";
    button.className = "day-cell";
    if (key === selectedDate) {
      button.classList.add("selected");
    }
    button.textContent = String(day);
    button.addEventListener("click", () => {
      selectedDate = key;
      renderCalendar();
      loadSelectedDay();
    });

    if (counts.get(key)) {
      const dot = document.createElement("span");
      dot.className = "dot";
      button.appendChild(dot);
    }

    calendarGrid.appendChild(button);
  }
}

async function loadAllEvents() {
  const res = await fetch("/api/events");
  const data = await res.json();
  allEvents = data.events || [];
}

async function loadSelectedDay() {
  selectedDateLabel.textContent = `Events for ${selectedDate}`;
  const res = await fetch(`/api/events?date=${encodeURIComponent(selectedDate)}`);
  const data = await res.json();
  const events = data.events || [];

  eventsList.innerHTML = "";
  if (events.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No events yet.";
    eventsList.appendChild(li);
    return;
  }

  events.forEach((evt) => {
    const li = document.createElement("li");
    li.className = "event-item";

    const meta = document.createElement("div");
    meta.className = "event-meta";

    const title = document.createElement("strong");
    title.textContent = evt.title;
    meta.appendChild(title);

    const time = document.createElement("span");
    time.className = "event-time";
    time.textContent = evt.time ? `Time: ${evt.time}` : "No time";
    meta.appendChild(time);

    const id = document.createElement("span");
    id.className = "event-time";
    id.textContent = `ID: ${evt.id}`;
    meta.appendChild(id);

    const removeButton = document.createElement("button");
    removeButton.className = "remove-btn";
    removeButton.type = "button";
    removeButton.textContent = "Remove";
    removeButton.addEventListener("click", async () => {
      await fetch(`/api/events/${encodeURIComponent(evt.id)}`, { method: "DELETE" });
      await refreshPlanner();
    });

    li.append(meta, removeButton);
    eventsList.appendChild(li);
  });
}

async function refreshPlanner() {
  await loadAllEvents();
  renderCalendar();
  await loadSelectedDay();
}

addEventForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = eventTitleInput.value.trim();
  const time = eventTimeInput.value;
  if (!title) {
    return;
  }

  await fetch("/api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: selectedDate, title, time }),
  });

  eventTitleInput.value = "";
  eventTimeInput.value = "";
  await refreshPlanner();
});

prevMonthBtn.addEventListener("click", () => {
  currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1);
  renderCalendar();
});

nextMonthBtn.addEventListener("click", () => {
  currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1);
  renderCalendar();
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) {
    return;
  }

  chatHistory.push({ role: "user", content: text });
  renderChat();
  chatInput.value = "";
  setChatWaiting(true);
  renderChat();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ history: chatHistory }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "Failed to get chat response");
    }

    const toolCalls = Array.isArray(data.tool_calls) ? data.tool_calls : [];
    toolCalls.forEach((call) => {
      chatHistory.push({ role: "tool_call", content: formatToolCall(call) });
    });
    chatHistory.push({ role: "assistant", content: data.reply || "" });
    renderChat();
    await refreshPlanner();
  } catch (err) {
    chatHistory.push({ role: "assistant", content: `Error: ${err.message}` });
  } finally {
    setChatWaiting(false);
    renderChat();
  }
});

async function init() {
  renderChat();
  await refreshPlanner();
}

init();
