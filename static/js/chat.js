(() => {
  const app = document.getElementById("chat-app");
  if (!app) return;

  const scroll = document.getElementById("chat-scroll");
  const list = document.getElementById("chat-messages");
  const loadOlderButton = document.getElementById("chat-load-older");
  const form = document.getElementById("chat-compose");
  const bodyInput = document.getElementById("chat-body");
  const connection = document.getElementById("chat-connection");
  const errorBox = document.getElementById("chat-error");
  const currentParticipantId = app.dataset.participantId;
  let hasMore = app.dataset.hasMore === "true";
  let loadingOlder = false;
  let socket = null;
  let retryDelay = 1000;
  let reconnectTimer = null;
  let intentionallyClosed = false;

  const messageNodes = () => [...list.querySelectorAll("[data-message-id]")];
  const oldestId = () => messageNodes()[0]?.dataset.messageId || null;
  const newestId = () => messageNodes().at(-1)?.dataset.messageId || null;
  const hasMessage = (id) => Boolean(list.querySelector(`[data-message-id="${id}"]`));
  const nearBottom = () => scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 100;

  function setConnection(text, state) {
    connection.textContent = text;
    connection.dataset.state = state;
  }

  function renderMessage(message, prepend = false) {
    if (hasMessage(message.id)) return;
    document.getElementById("chat-empty")?.remove();
    const own = message.participant.id === currentParticipantId;
    const article = document.createElement("article");
    article.className = `chat-message${own ? " chat-message-own" : ""}`;
    article.dataset.messageId = message.id;

    const avatar = document.createElement("span");
    avatar.className = "chat-avatar";
    avatar.style.setProperty("--avatar-hue", message.participant.avatar_hue);
    avatar.textContent = message.participant.display_name.slice(-2);

    const content = document.createElement("div");
    content.className = "chat-message-content";
    const meta = document.createElement("div");
    meta.className = "chat-message-meta";
    const name = document.createElement("strong");
    name.textContent = message.participant.display_name;
    const ip = document.createElement("span");
    ip.textContent = message.participant.masked_ip;
    const time = document.createElement("time");
    const createdAt = new Date(message.created_at);
    time.dateTime = message.created_at;
    time.textContent = createdAt.toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"
    });
    meta.append(name, ip, time);
    const text = document.createElement("p");
    text.textContent = message.body;
    content.append(meta, text);
    article.append(avatar, content);
    prepend ? list.prepend(article) : list.append(article);
  }

  async function fetchMessages(params) {
    const url = new URL(app.dataset.historyUrl, window.location.href);
    Object.entries(params).forEach(([key, value]) => {
      if (value) url.searchParams.set(key, value);
    });
    const response = await fetch(url, {credentials: "same-origin", cache: "no-store"});
    if (!response.ok) throw new Error("无法获取聊天记录");
    return response.json();
  }

  async function loadOlder() {
    if (loadingOlder || !hasMore || !oldestId()) return;
    loadingOlder = true;
    loadOlderButton.disabled = true;
    const previousHeight = scroll.scrollHeight;
    try {
      const data = await fetchMessages({before: oldestId()});
      [...data.messages].reverse().forEach((message) => renderMessage(message, true));
      hasMore = data.has_more;
      loadOlderButton.hidden = !hasMore;
      scroll.scrollTop += scroll.scrollHeight - previousHeight;
    } catch (error) {
      errorBox.textContent = error.message;
    } finally {
      loadingOlder = false;
      loadOlderButton.disabled = false;
    }
  }

  async function catchUp() {
    let cursor = newestId();
    if (!cursor) return;
    let more = true;
    while (more) {
      const data = await fetchMessages({after: cursor});
      const shouldStick = nearBottom();
      data.messages.forEach((message) => renderMessage(message));
      if (shouldStick) scroll.scrollTop = scroll.scrollHeight;
      cursor = newestId();
      more = data.has_more && data.messages.length > 0;
    }
  }

  function connect() {
    if (intentionallyClosed) return;
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${window.location.host}${app.dataset.websocketPath}`);
    setConnection("正在连接…", "connecting");

    socket.addEventListener("open", async () => {
      retryDelay = 1000;
      setConnection("实时连接正常", "online");
      try { await catchUp(); } catch (_error) { errorBox.textContent = "补拉消息失败，将自动重试。"; }
    });

    socket.addEventListener("message", (event) => {
      let payload;
      try { payload = JSON.parse(event.data); } catch (_error) { return; }
      if (payload.type === "message") {
        const shouldStick = nearBottom() || payload.message.participant.id === currentParticipantId;
        renderMessage(payload.message);
        if (shouldStick) scroll.scrollTop = scroll.scrollHeight;
        errorBox.textContent = "";
      } else if (payload.type === "error") {
        errorBox.textContent = payload.message;
      } else if (payload.type === "room_closed") {
        intentionallyClosed = true;
        setConnection(payload.message, "offline");
        bodyInput.disabled = true;
        form.querySelector("button").disabled = true;
      }
    });

    socket.addEventListener("close", (event) => {
      socket = null;
      if (intentionallyClosed || event.code === 4403) {
        intentionallyClosed = true;
        setConnection("会话已失效，请重新输入授权码", "offline");
        bodyInput.disabled = true;
        form.querySelector("button").disabled = true;
        return;
      }
      setConnection("连接中断，正在重连…", "offline");
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 15000);
    });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const body = bodyInput.value.trim();
    if (!body) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      errorBox.textContent = "连接尚未恢复，请稍后再试。";
      return;
    }
    const clientNonce = crypto.randomUUID
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
          const value = Math.random() * 16 | 0;
          return (character === "x" ? value : (value & 3 | 8)).toString(16);
        });
    socket.send(JSON.stringify({type: "message", body, client_nonce: clientNonce}));
    bodyInput.value = "";
    bodyInput.focus();
  });

  bodyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  loadOlderButton.addEventListener("click", loadOlder);
  scroll.addEventListener("scroll", () => {
    if (scroll.scrollTop < 80) loadOlder();
  });

  setInterval(async () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      try { await catchUp(); } catch (_error) { /* next interval retries */ }
    }
  }, 5000);

  scroll.scrollTop = scroll.scrollHeight;
  loadOlderButton.hidden = !hasMore;
  connect();
})();
