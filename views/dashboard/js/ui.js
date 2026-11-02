// 通用界面工具：DOM 构建、提示、确认框、报告查看器、格式化
// 插件页面运行在沙箱 iframe 中，confirm/alert 不可用，这里自己实现弹窗

/** 创建元素；文本一律走 textContent，避免群名等内容注入 HTML */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function toast(message, type = "info") {
  const node = el("div", { class: `toast ${type}`, text: message });
  document.getElementById("toast-root").append(node);
  setTimeout(() => node.remove(), type === "error" ? 6000 : 3000);
}

function openModal(content, wide = false) {
  const modal = el("div", { class: wide ? "modal wide" : "modal" }, content);
  const mask = el("div", { class: "modal-mask" }, modal);
  mask.addEventListener("click", (e) => {
    if (e.target === mask) mask.remove();
  });
  document.body.append(mask);
  return mask;
}

/** 二次确认，返回 Promise<boolean> */
export function confirmDialog(message, okText = "确定", danger = true) {
  return new Promise((resolve) => {
    let mask;
    const close = (result) => {
      mask.remove();
      resolve(result);
    };
    mask = openModal([
      el("p", { text: message }),
      el("div", { class: "foot" }, [
        el("button", { class: "btn", text: "取消", onclick: () => close(false) }),
        el("button", {
          class: danger ? "btn danger" : "btn primary",
          text: okText,
          onclick: () => close(true),
        }),
      ]),
    ]);
  });
}

/** 在弹窗里用隔离的 iframe 展示一份报告 HTML（允许脚本，但不与插件页面同源） */
export function showHtmlViewer(title, html, extraButtons = []) {
  let mask;
  const frame = el("iframe", { sandbox: "allow-scripts", title });
  frame.srcdoc = html;
  mask = openModal(
    [
      el("div", { class: "head" }, [
        el("strong", { text: title }),
        el("div", { class: "actions" }, [
          ...extraButtons,
          el("button", { class: "btn", text: "关闭", onclick: () => mask.remove() }),
        ]),
      ]),
      frame,
    ],
    true,
  );
}

/** 剪贴板在沙箱里可能不可用，失败时弹出可全选复制的文本框 */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制", "success");
    return;
  } catch {
    // 回退到手动复制
  }
  const box = el("textarea", { class: "copy-box", readonly: true });
  box.value = text;
  let mask;
  mask = openModal(
    [
      el("p", { text: "浏览器不允许直接写入剪贴板，请按 Ctrl+C 复制下面已选中的内容。" }),
      box,
      el("div", { class: "foot", style: "margin-top:10px" }, [
        el("button", { class: "btn", text: "关闭", onclick: () => mask.remove() }),
      ]),
    ],
    true,
  );
  box.focus();
  box.select();
}

export function formatTime(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function formatDuration(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  if (s < 60) return `${s} 秒`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分 ${s % 60} 秒`;
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`;
}

export const SOURCE_LABELS = {
  manual: "手动",
  scheduled: "定时",
  incremental: "增量",
  incremental_report: "增量报告",
};

export function emptyRow(colspan, text) {
  return el("tr", {}, el("td", { colspan, class: "empty", text }));
}
