export function resizeChatComposerTextarea(textarea: HTMLTextAreaElement) {
  textarea.style.height = "auto";
  const contentHeight = textarea.scrollHeight;
  textarea.style.height = `${contentHeight}px`;
  textarea.style.overflowY = contentHeight > textarea.clientHeight ? "auto" : "hidden";
}

export function snapChatComposerScroll(textarea: HTMLTextAreaElement) {
  const lineHeight = Number.parseFloat(window.getComputedStyle(textarea).lineHeight);
  if (!Number.isFinite(lineHeight) || lineHeight <= 0) return;

  const maxScrollTop = Math.max(0, textarea.scrollHeight - textarea.clientHeight);
  const maxAlignedScrollTop = Math.floor(maxScrollTop / lineHeight) * lineHeight;
  const alignedScrollTop = Math.min(
    maxAlignedScrollTop,
    Math.max(0, Math.round(textarea.scrollTop / lineHeight) * lineHeight),
  );
  if (Math.abs(textarea.scrollTop - alignedScrollTop) > 0.5) {
    textarea.scrollTop = alignedScrollTop;
  }
}
