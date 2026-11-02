// 插件日志：按级别、关键字筛选，自动刷新，复制全部
import { api } from "./api.js";
import { copyText, el, formatTime } from "./ui.js";

const POLL_MS = 3000;
const MAX_LINES = 2000;

export function createLogsPage(root) {
  let entries = [];
  let lastId = 0;
  let timer = null;
  let active = false;

  const levelSelect = el(
    "select",
    { onchange: reload },
    ["", "DEBUG", "INFO", "WARNING", "ERROR"].map((lv) => el("option", { value: lv, text: lv ? `${lv} 及以上` : "全部级别" })),
  );
  const keywordInput = el("input", { type: "text", placeholder: "关键字 / TraceID", style: "width:220px" });
  keywordInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") reload();
  });
  const autoBox = el("input", { type: "checkbox", checked: true, onchange: schedule });
  const list = el("div", { class: "log-list" });
  const countInfo = el("span", { class: "muted" });

  root.append(
    el("div", { class: "card" }, [
      el("div", { class: "toolbar" }, [
        levelSelect,
        keywordInput,
        el("button", { class: "btn primary", text: "筛选", onclick: reload }),
        el("label", { class: "inline" }, [autoBox, "自动刷新"]),
        el("button", { class: "btn", text: "复制全部", onclick: () => copyText(entries.map(lineText).join("\n")) }),
        countInfo,
      ]),
      list,
    ]),
  );

  function lineText(e) {
    return `${formatTime(e.time)} [${e.level}] [${e.trace_id}] ${e.message}`;
  }

  function lineNode(e) {
    return el("div", { class: `log-line ${e.level}` }, [
      el("span", { class: "muted", text: `${formatTime(e.time)} ` }),
      el("span", { class: "lv", text: e.level }),
      el("span", { class: "muted", text: `[${e.trace_id}] ` }),
      e.message,
    ]);
  }

  async function fetchNew() {
    const data = await api.get("logs", {
      level: levelSelect.value,
      keyword: keywordInput.value.trim(),
      after: lastId,
    });
    const fresh = data.entries || [];
    if (!fresh.length) return;
    // 只有在已经滚到底部时才自动跟随新日志
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    // 之前是空列表（可能显示着「没有日志」提示），先清掉
    if (!entries.length) list.replaceChildren();
    entries = entries.concat(fresh).slice(-MAX_LINES);
    lastId = fresh[fresh.length - 1].id;
    list.append(...fresh.map(lineNode));
    while (list.childElementCount > MAX_LINES) list.firstElementChild.remove();
    countInfo.textContent = `${entries.length} 条`;
    if (atBottom) list.scrollTop = list.scrollHeight;
  }

  async function reload() {
    entries = [];
    lastId = 0;
    list.replaceChildren();
    countInfo.textContent = "";
    try {
      await fetchNew();
      if (!entries.length) list.replaceChildren(el("div", { class: "empty", text: "没有符合条件的日志" }));
      list.scrollTop = list.scrollHeight;
    } catch (e) {
      list.replaceChildren(el("div", { class: "empty", text: `加载失败：${e.message}` }));
    }
  }

  function schedule() {
    clearTimeout(timer);
    if (active && autoBox.checked && !document.hidden) {
      timer = setTimeout(async () => {
        try {
          await fetchNew();
        } catch {
          // 下次再试
        }
        schedule();
      }, POLL_MS);
    }
  }

  document.addEventListener("visibilitychange", schedule);

  return {
    async activate() {
      active = true;
      await reload();
      schedule();
    },
    deactivate() {
      active = false;
      clearTimeout(timer);
    },
  };
}
