// 插件页面入口：等待 bridge 就绪后挂载四个标签页
import { ready } from "./api.js";
import { createLogsPage } from "./logs.js";
import { createReportsPage } from "./reports.js";
import { createTasksPage } from "./tasks.js";
import { createTemplatesPage } from "./templates.js";

await ready();

const pages = {
  reports: createReportsPage(document.getElementById("tab-reports")),
  templates: createTemplatesPage(document.getElementById("tab-templates")),
  tasks: createTasksPage(document.getElementById("tab-tasks")),
  logs: createLogsPage(document.getElementById("tab-logs")),
};

let current = null;

function switchTo(name) {
  if (current === name) return;
  if (current) pages[current].deactivate();
  current = name;
  for (const btn of document.querySelectorAll("#tabs button")) {
    btn.classList.toggle("active", btn.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab-panel")) {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  }
  pages[name].activate();
}

document.getElementById("tabs").addEventListener("click", (e) => {
  const tab = e.target.closest("button")?.dataset.tab;
  if (tab) switchTo(tab);
});

switchTo("reports");
