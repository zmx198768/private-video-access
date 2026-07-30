(() => {
  const EMOJI_LIST = [
    "😀", "😄", "😁", "😂", "🤣", "😊", "😍", "🥰",
    "😘", "😎", "🤔", "🤗", "🤭", "😅", "🥹", "😭",
    "😡", "😴", "🙄", "😮", "👍", "👎", "👏", "🙌",
    "🙏", "💪", "🤝", "👌", "✌️", "❤️", "💔", "💯",
    "🔥", "🎉", "✨", "🌹", "🌟", "☕", "🍻", "🎂",
    "🎁", "🚀", "💡", "✅", "❌", "⚠️", "📌", "👀"
  ];
  const app = document.getElementById("chat-app");
  if (!app) return;

  const scroll = document.getElementById("chat-scroll");
  const list = document.getElementById("chat-messages");
  const loadOlderButton = document.getElementById("chat-load-older");
  const form = document.getElementById("chat-compose");
  const bodyInput = document.getElementById("chat-body");
  const sendButton = document.getElementById("chat-send");
  const emojiToggle = document.getElementById("chat-emoji-toggle");
  const emojiPicker = document.getElementById("chat-emoji-picker");
  const imageInput = document.getElementById("chat-image-input");
  const imageLabel = document.getElementById("chat-image-label");
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
  const messageImageUrl = (messageId) => `${app.dataset.imageBaseUrl}image/${messageId}/`;

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
    content.append(meta);
    if (message.image?.present) {
      const imageLink = document.createElement("a");
      imageLink.className = "chat-message-image";
      imageLink.href = messageImageUrl(message.id);
      imageLink.target = "_blank";
      imageLink.rel = "noopener";
      const image = document.createElement("img");
      image.src = imageLink.href;
      image.alt = `由${message.participant.display_name}发送的聊天图片`;
      image.loading = "lazy";
      image.width = message.image.width;
      image.height = message.image.height;
      imageLink.append(image);
      content.append(imageLink);
    }
    if (message.body) {
      const text = document.createElement("p");
      text.textContent = message.body;
      content.append(text);
    }
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
        sendButton.disabled = true;
        emojiToggle.disabled = true;
        imageInput.disabled = true;
      }
    });

    socket.addEventListener("close", (event) => {
      socket = null;
      if (intentionallyClosed || event.code === 4403) {
        intentionallyClosed = true;
        setConnection("会话已失效，请重新输入授权码", "offline");
        bodyInput.disabled = true;
        sendButton.disabled = true;
        emojiToggle.disabled = true;
        imageInput.disabled = true;
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

  function insertEmoji(emoji) {
    const start = bodyInput.selectionStart;
    const end = bodyInput.selectionEnd;
    const available = bodyInput.maxLength - (bodyInput.value.length - (end - start));
    const insertion = emoji.slice(0, Math.max(0, available));
    bodyInput.setRangeText(insertion, start, end, "end");
    bodyInput.focus();
  }

  EMOJI_LIST.forEach((emoji) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = emoji;
    button.setAttribute("aria-label", `插入表情 ${emoji}`);
    button.addEventListener("click", () => insertEmoji(emoji));
    emojiPicker.append(button);
  });

  emojiToggle.addEventListener("click", () => {
    const opening = emojiPicker.hidden;
    emojiPicker.hidden = !opening;
    emojiToggle.setAttribute("aria-expanded", String(opening));
  });
  document.addEventListener("click", (event) => {
    if (!emojiPicker.hidden && !emojiPicker.contains(event.target) && !emojiToggle.contains(event.target)) {
      emojiPicker.hidden = true;
      emojiToggle.setAttribute("aria-expanded", "false");
    }
  });

  async function uploadImage(file) {
    if (!file || intentionallyClosed) return;
    imageInput.disabled = true;
    imageLabel.dataset.uploading = "true";
    errorBox.textContent = "图片上传中…";
    const formData = new FormData();
    formData.append("image", file);
    try {
      const response = await fetch(app.dataset.uploadUrl, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: {
          "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
          "X-Requested-With": "XMLHttpRequest"
        }
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || "图片上传失败");
      renderMessage(payload.message);
      scroll.scrollTop = scroll.scrollHeight;
      errorBox.textContent = "";
    } catch (error) {
      errorBox.textContent = error.message;
    } finally {
      imageInput.value = "";
      imageInput.disabled = false;
      delete imageLabel.dataset.uploading;
    }
  }

  imageInput.addEventListener("change", () => uploadImage(imageInput.files[0]));

  bodyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit(sendButton);
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
