const state = {
  username: null,
  recipient: "",       // "" = public
  typingTimeout: null,
  pollTimer: null,
};

const $ = (id) => document.getElementById(id);

// ================= TAB SWITCHING =================
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(btn.dataset.tab + "-tab").classList.add("active");
  });
});

// ================= AUTH =================
$("reg-btn").addEventListener("click", async () => {
  const username = $("reg-username").value.trim();
  const password = $("reg-password").value;
  const res = await fetch("/api/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json();
  $("reg-msg").textContent = data.message;
  $("reg-msg").style.color = data.success ? "#2a2" : "#d33";
});

$("login-btn").addEventListener("click", async () => {
  const username = $("login-username").value.trim();
  const password = $("login-password").value;
  const res = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json();
  if (data.success) {
    startChat(data.username);
  } else {
    $("login-msg").textContent = data.message || "Login failed";
  }
});

$("logout-btn").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  clearInterval(state.pollTimer);
  location.reload();
});

async function checkSession() {
  const res = await fetch("/api/me");
  const data = await res.json();
  if (data.logged_in) startChat(data.username);
}

function startChat(username) {
  state.username = username;
  $("auth-screen").classList.add("hidden");
  $("chat-screen").classList.remove("hidden");
  $("me-label").textContent = "👤 " + username;
  loadUsers();
  poll();
  state.pollTimer = setInterval(poll, 2000);
}

// ================= RECIPIENT SELECT (FIXED & HYBRID SYNCHRONIZED) =================
async function loadUsers() {
  const res = await fetch("/api/users");
  const data = await res.json();
  const select = $("recipient-select");
  
  // Track current selection focus so we don't snap people back to public room mid-chat
  const currentSelection = state.recipient;
  
  select.innerHTML = '<option value="">🌐 All (public)</option>';
  
  data.users.forEach((u) => {
    // Prevent rendering yourself in the private direct message option selection block
    if (u !== state.username) {
      const opt = document.createElement("option");
      opt.value = u;
      opt.textContent = `🔒 Private: ${u}`;
      select.appendChild(opt);
    }
  });

  // Reapply previous focus cleanly
  select.value = currentSelection;
  if (!select.value) {
    select.value = "";
    state.recipient = "";
  }
}

$("recipient-select").addEventListener("change", (e) => {
  state.recipient = e.target.value;
  $("chat-title").textContent = state.recipient
    ? `🔒 Private Chat with ${state.recipient}`
    : "🌐 Public Chat";
  $("video-section").classList.toggle("hidden", !state.recipient);
  
  // Close the mobile drawer panel automatically on mobile viewport interactions
  const mobileToggle = $("sidebar-toggle");
  if (mobileToggle && window.innerWidth <= 768) {
    mobileToggle.checked = false;
  }

  refreshMessages();
  refreshVideoStatus();
});

// Auto-close retractable mobile view sidebar when tapping on main chat messages workspace
document.querySelector(".chat-main").addEventListener("click", () => {
  const mobileToggle = $("sidebar-toggle");
  if (mobileToggle && window.innerWidth <= 768) {
    mobileToggle.checked = false;
  }
});

// ================= CLEAR CHAT =================
$("clear-btn").addEventListener("click", async () => {
  await fetch("/api/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recipient: state.recipient || null }),
  });
  refreshMessages();
});

// ================= TYPING =================
$("chat-input").addEventListener("input", () => {
  const typing = $("chat-input").value.trim().length > 0;
  fetch("/api/typing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ typing }),
  });
});

// ================= SEND MESSAGE =================
async function sendMessage() {
  const message = $("chat-input").value.trim();
  if (!message) return;
  await fetch("/api/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, recipient: state.recipient || null }),
  });
  $("chat-input").value = "";
  fetch("/api/typing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ typing: false }),
  });
  refreshMessages();
}

$("send-btn").addEventListener("click", sendMessage);
$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// ================= FILE UPLOAD =================
$("send-file-btn").addEventListener("click", async () => {
  const file = $("file-input").files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  formData.append("recipient", state.recipient || "");
  await fetch("/api/upload", { method: "POST", body: formData });
  $("file-input").value = "";
  refreshMessages();
});

// ================= POLLING =================
async function poll() {
  await refreshOnline();
  await loadUsers(); // Repeatedly synchronizes active available user arrays to drop options smoothly
  await refreshMessages();
  await refreshTyping();
  if (state.recipient) await refreshVideoStatus();
}

async function refreshOnline() {
  const res = await fetch("/api/heartbeat", { method: "POST" });
  const data = await res.json();
  $("online-count").textContent = `🟢 Online Users (${data.online.length})`;
  $("online-list").innerHTML = data.online.map((u) => `<li>🟢 ${escapeHtml(u)}</li>`).join("");
}

async function refreshTyping() {
  const res = await fetch("/api/typing");
  const data = await res.json();
  const others = data.typing.filter((u) => (state.recipient ? u === state.recipient : true));
  $("typing-indicator").textContent = others.length ? "✍️ " + others.join(", ") + " typing…" : "";
}

async function refreshMessages() {
  const res = await fetch(`/api/messages?recipient=${encodeURIComponent(state.recipient)}`);
  const data = await res.json();
  renderMessages(data.messages);
}

function renderMessages(messages) {
  const box = $("chat-box");
  const wasAtBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;

  box.innerHTML = messages
    .map((m) => {
      const me = m.user === state.username;
      const avatar = `<div class="avatar">${escapeHtml(m.user[0].toUpperCase())}</div>`;
      let content;
      if (m.msg_type === "text") {
        content = escapeHtml(m.message);
      } else if (m.file_name && /\.(png|jpg|jpeg)$/i.test(m.file_name)) {
        content = `<img src="/api/download/${m.id}" alt="${escapeHtml(m.file_name)}">`;
      } else {
        content = `<a href="/api/download/${m.id}" download="${escapeHtml(m.file_name)}">${escapeHtml(m.file_name)}</a>`;
      }
      const privLabel = state.recipient ? "(private)" : "";
      return `
        <div class="msg-row ${me ? "me" : "them"}">
          ${me ? "" : avatar}
          <div class="bubble ${me ? "me" : "them"}">
            <b>${escapeHtml(m.user)} ${privLabel}</b><br>${content}
            <div class="ts">${escapeHtml(m.timestamp)}</div>
          </div>
          ${me ? avatar : ""}
        </div>`;
    })
    .join("");

  if (wasAtBottom) box.scrollTop = box.scrollHeight;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ================= VIDEO CALLS =================
async function refreshVideoStatus() {
  if (!state.recipient) return;
  const res = await fetch(`/api/video/status?recipient=${encodeURIComponent(state.recipient)}`);
  const data = await res.json();
  const controls = $("video-controls");

  if (data.started) {
    controls.innerHTML = `
      <p>Active Call: Room <code>${escapeHtml(data.room_name)}</code></p>
      <a class="primary-btn" style="display:block;text-align:center;text-decoration:none;" target="_blank" href="https://meet.jit.si/${encodeURIComponent(data.room_name)}">Join Video Call</a>
      <button id="end-call-btn" class="secondary-btn">End Video Call</button>
    `;
    $("end-call-btn").addEventListener("click", async () => {
      await fetch("/api/video/end", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_name: data.room_name }),
      });
      refreshVideoStatus();
    });
  } else {
    controls.innerHTML = `<button id="start-call-btn" class="primary-btn">Start Video Call</button>`;
    $("start-call-btn").addEventListener("click", async () => {
      const res2 = await fetch("/api/video/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipient: state.recipient }),
      });
      const data2 = await res2.json();
      if (data2.success) {
        window.open(`https://meet.jit.si/${data2.room_name}`, "_blank");
        refreshVideoStatus();
      }
    });
  }
}

// ================= INIT =================
checkSession();
