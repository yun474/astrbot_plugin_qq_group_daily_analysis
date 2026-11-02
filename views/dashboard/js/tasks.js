// 任务状态：正在运行的分析任务（可停止）、增量计数、最近任务
import { api, seg } from "./api.js";
import { confirmDialog, el, emptyRow, formatDuration, formatTime, toast } from "./ui.js";

const POLL_MS = 3000;

const STATUS = {
  success: ["成功", "success"],
  failed: ["失败", "danger"],
  stopped: ["已停止", "warning"],
  skipped: ["跳过", "gray"],
  running: ["运行中", ""],
};

export function createTasksPage(root) {
  let timer = null;
  let active = false;
  const runningBody = el("tbody");
  const incrBody = el("tbody");
  const historyBody = el("tbody");
  const incrCard = el("div", { class: "card", style: "display:none" }, [
    el("h2", { text: "增量消息计数" }),
    el("table", {}, [
      el("thead", {}, el("tr", {}, ["群", "新消息 / 触发条数", "状态"].map((t) => el("th", { text: t })))),
      incrBody,
    ]),
  ]);

  root.append(
    el("div", { class: "card" }, [
      el("h2", { text: "正在运行" }),
      el("table", {}, [
        el("thead", {}, el("tr", {}, ["群", "来源", "当前阶段", "已用时间", "操作"].map((t) => el("th", { text: t })))),
        runningBody,
      ]),
    ]),
    incrCard,
    el("div", { class: "card" }, [
      el("h2", { text: "最近任务（最多 50 条）" }),
      el("table", {}, [
        el("thead", {}, el("tr", {}, ["开始时间", "群", "来源", "状态", "耗时", "说明"].map((t) => el("th", { text: t })))),
        historyBody,
      ]),
    ]),
  );

  const groupCell = (t) => el("td", {}, [t.group_name || "", el("div", { class: "muted", text: t.group_id })]);

  async function stop(task) {
    const ok = await confirmDialog(`确定停止群 ${task.group_name || task.group_id} 的${task.source_label}分析吗？`, "停止");
    if (!ok) return;
    try {
      await api.post(`tasks/${seg(task.task_id)}/stop`);
      toast("已发送停止请求", "success");
      refresh();
    } catch (e) {
      toast(`停止失败：${e.message}`, "error");
    }
  }

  function render(data) {
    runningBody.replaceChildren(
      ...(data.running.length
        ? data.running.map((t) =>
            el("tr", {}, [
              groupCell(t),
              el("td", {}, el("span", { class: "badge", text: t.source_label })),
              el("td", { text: t.stage }),
              el("td", { text: formatDuration(t.duration) }),
              el("td", {}, el("button", { class: "btn small danger", text: "停止", onclick: () => stop(t) })),
            ]),
          )
        : [emptyRow(5, "当前没有正在运行的分析任务")]),
    );

    incrCard.style.display = data.incremental.length ? "" : "none";
    incrBody.replaceChildren(
      ...data.incremental.map((s) =>
        el("tr", {}, [
          el("td", { text: s.group_id }),
          el("td", { text: `${s.count} / ${s.threshold}` }),
          el("td", {
            text: s.running ? "分析中" : s.cooldown_seconds ? `失败冷却中（${formatDuration(s.cooldown_seconds)}）` : "等待中",
          }),
        ]),
      ),
    );

    historyBody.replaceChildren(
      ...(data.history.length
        ? data.history.map((t) => {
            const [label, cls] = STATUS[t.status] || [t.status, "gray"];
            return el("tr", {}, [
              el("td", { text: formatTime(t.started_at) }),
              groupCell(t),
              el("td", {}, el("span", { class: "badge", text: t.source_label })),
              el("td", {}, el("span", { class: `badge ${cls}`, text: label })),
              el("td", { text: formatDuration(t.duration) }),
              el("td", { class: "muted", text: t.error || "" }),
            ]);
          })
        : [emptyRow(6, "还没有任务记录")]),
    );
  }

  async function refresh() {
    try {
      render(await api.get("tasks"));
    } catch (e) {
      runningBody.replaceChildren(emptyRow(5, `加载失败：${e.message}`));
    }
  }

  function schedule() {
    clearTimeout(timer);
    if (active && !document.hidden) timer = setTimeout(tick, POLL_MS);
  }

  async function tick() {
    await refresh();
    schedule();
  }

  // 页面不可见时暂停轮询
  document.addEventListener("visibilitychange", () => {
    if (!active) return;
    if (document.hidden) clearTimeout(timer);
    else tick();
  });

  return {
    activate() {
      active = true;
      tick();
    },
    deactivate() {
      active = false;
      clearTimeout(timer);
    },
  };
}
