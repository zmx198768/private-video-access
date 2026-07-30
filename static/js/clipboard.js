(() => {
  const legacyCopy = (value) => {
    const area = document.createElement("textarea");
    const activeElement = document.activeElement;
    const selection = window.getSelection();
    const savedRanges = [];
    if (selection) {
      for (let index = 0; index < selection.rangeCount; index += 1) {
        savedRanges.push(selection.getRangeAt(index).cloneRange());
      }
    }

    area.value = value;
    area.setAttribute("readonly", "");
    area.setAttribute("aria-hidden", "true");
    area.style.position = "fixed";
    area.style.inset = "0 auto auto -9999px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    area.setSelectionRange(0, area.value.length);

    let copied = false;
    try {
      copied = document.execCommand("copy");
    } finally {
      area.remove();
      if (activeElement && typeof activeElement.focus === "function") {
        activeElement.focus({preventScroll: true});
      }
      if (selection) {
        selection.removeAllRanges();
        savedRanges.forEach((range) => selection.addRange(range));
      }
    }
    if (!copied) throw new Error("legacy clipboard copy failed");
  };

  window.copyTextWithFallback = async (value) => {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(value);
        return;
      } catch (_error) {
        // Permission policies can reject the modern API even in a secure context.
      }
    }
    legacyCopy(value);
  };
})();
