// 报告历史：按群、日期筛选，查看、下载、删除归档的报告
import { api, seg } from "./api.js";
import {
  confirmDialog,
  el,
  emptyRow,
  formatTime,
  showHtmlViewer,
  SOURCE_LABELS,
  toast,
} from "./ui.js";

export function createReportsPage(root) {
  const state = { page: 1, total: 0, pageSize: 20, groupsLoaded: false };

  const groupSelect = el("select", {}, el("option", { value: "", text: "全部群" }));
  const startInput = el("input", { type: "date" });
  const endInput = el("input", { type: "date" });
  const tbody = el("tbody");
  const pageInfo = el("span", { class: "muted" });
  const prevBtn = el("button", { class: "btn small", text: "上一页", onclick: () => go(-1) });
  const nextBtn = el("button", { class: "btn small", text: "下一页", onclick: () => go(1) });

  root.append(
    el("div", { class: "card" }, [
      el("div", { class: "toolbar" }, [
        groupSelect,
        el("label", { class: "inline" }, ["从", startInput]),
        el("label", { class: "inline" }, ["到", endInput]),
        el("button", {
          class: "btn primary",
          text: "查询",
          onclick: () => {
            state.page = 1;
            load();
          },
        }),
        el("button", {
          class: "btn",
          text: "重置",
          onclick: () => {
            groupSelect.value = "";
            startInput.value = "";
            endInput.value = "";
            state.page = 1;
            load();
          },
        }),
      ]),
      el("table", {}, [
        el(
          "thead",
          {},
          el("tr", {}, ["生成时间", "群", "模板", "来源", "消息数", "参与人数", "操作"].map((t) => el("th", { text: t }))),
        ),
        tbody,
      ]),
      el("div", { class: "pager" }, [pageInfo, prevBtn, nextBtn]),
    ]),
  );

  function go(delta) {
    state.page += delta;
    load();
  }

  function fillGroups(groups) {
    const current = groupSelect.value;
    groupSelect.replaceChildren(el("option", { value: "", text: "全部群" }));
    for (const g of groups) {
      const label = g.group_name ? `${g.group_name}（${g.group_id}）` : g.group_id;
      groupSelect.append(el("option", { value: g.group_id, text: label }));
    }
    groupSelect.value = current;
  }

  async function view(item) {
    try {
      const data = await api.get(`reports/${seg(item.id)}`);
      const title = `${item.group_name || item.group_id} · ${formatTime(item.created_at)}`;
      showHtmlViewer(title, data.html, [
        el("button", { class: "btn", text: "下载", onclick: () => download(item) }),
      ]);
    } catch (e) {
      toast(`打开报告失败：${e.message}`, "error");
    }
  }

  async function download(item) {
    try {
      await api.download(`reports/${seg(item.id)}/download`, {}, `群分析报告_${item.group_id}_${item.id}.html`);
    } catch (e) {
      toast(`下载失败：${e.message}`, "error");
    }
  }

  async function remove(item) {
    const ok = await confirmDialog(`确定删除 ${formatTime(item.created_at)} 这份报告吗？删除后无法恢复。`, "删除");
    if (!ok) return;
    try {
      await api.post(`reports/${seg(item.id)}/delete`);
      toast("已删除", "success");
      load();
    } catch (e) {
      toast(`删除失败：${e.message}`, "error");
    }
  }

  function renderRows(items) {
    if (!items.length) {
      tbody.replaceChildren(emptyRow(7, "暂无报告。每次报告成功生成后会自动归档到这里。"));
      return;
    }
    tbody.replaceChildren(
      ...items.map((item) =>
        el("tr", {}, [
          el("td", { text: formatTime(item.created_at) }),
          el("td", {}, [item.group_name || "", el("div", { class: "muted", text: item.group_id })]),
          el("td", { text: item.template || "-" }),
          el("td", {}, el("span", { class: "badge", text: SOURCE_LABELS[item.source] || item.source || "-" })),
          el("td", { text: item.message_count }),
          el("td", { text: item.participant_count }),
          el(
            "td",
            {},
            el("div", { class: "actions" }, [
              el("button", { class: "btn small", text: "查看", onclick: () => view(item) }),
              el("button", { class: "btn small", text: "下载", onclick: () => download(item) }),
              el("button", { class: "btn small danger", text: "删除", onclick: () => remove(item) }),
            ]),
          ),
        ]),
      ),
    );
  }

  async function load() {
    try {
      const data = await api.get("reports", {
        group_id: groupSelect.value,
        start: startInput.value,
        end: endInput.value,
        page: state.page,
      });
      state.total = data.total;
      state.pageSize = data.page_size;
      const pages = Math.max(1, Math.ceil(data.total / data.page_size));
      if (state.page > pages) {
        state.page = pages;
        return load();
      }
      fillGroups(data.groups || []);
      renderRows(data.items || []);
      pageInfo.textContent = `共 ${data.total} 份，第 ${state.page} / ${pages} 页`;
      prevBtn.disabled = state.page <= 1;
      nextBtn.disabled = state.page >= pages;
    } catch (e) {
      tbody.replaceChildren(emptyRow(7, `加载失败：${e.message}`));
    }
  }

  return { activate: load, deactivate() {} };
}
