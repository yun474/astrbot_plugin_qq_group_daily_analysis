// 模板管理：预览、设为默认、从 GitHub / zip 安装、卸载自定义模板
import { api, seg } from "./api.js";
import { confirmDialog, el, showHtmlViewer, toast } from "./ui.js";

export function createTemplatesPage(root) {
  const grid = el("div", { class: "tpl-grid" });
  const currentInfo = el("span", { class: "muted" });

  const urlInput = el("input", { type: "text", placeholder: "https://github.com/用户名/仓库名", style: "flex:1;min-width:260px" });
  const nameInput = el("input", { type: "text", placeholder: "模板名（可选）", style: "width:160px" });
  const installBtn = el("button", { class: "btn primary", text: "从 GitHub 安装", onclick: installFromGithub });
  const fileInput = el("input", { type: "file", accept: ".zip,application/zip", style: "display:none", onchange: uploadZip });
  const uploadBtn = el("button", { class: "btn", text: "上传 zip 安装", onclick: () => fileInput.click() });

  root.append(
    el("div", { class: "card" }, [
      el("h2", { text: "安装自定义模板" }),
      el("div", { class: "toolbar" }, [urlInput, nameInput, installBtn, uploadBtn, fileInput]),
      el("div", {
        class: "muted",
        text:
          "模板目录里必须有 image_template.html，建议同时提供 topic_item.html、user_title_item.html、quote_item.html、activity_chart.html、chat_quality_item.html，缺少的板块会空白。" +
          "不能和内置模板重名；zip 文件直接放在根目录时，以 zip 文件名作为模板名。安装后立即可用，无需重启。",
      }),
    ]),
    el("div", { class: "card" }, [
      el("div", { class: "toolbar" }, [el("h2", { text: "全部模板", style: "margin:0" }), currentInfo]),
      grid,
    ]),
  );

  function setBusy(busy) {
    installBtn.disabled = busy;
    uploadBtn.disabled = busy;
  }

  function reportInstalled(result) {
    let msg = `模板「${result.name}」安装成功`;
    if (result.missing && result.missing.length) {
      msg += `，但缺少 ${result.missing.join("、")}，对应板块会空白`;
    }
    toast(msg, result.missing && result.missing.length ? "info" : "success");
  }

  async function installFromGithub() {
    const url = urlInput.value.trim();
    if (!url) return toast("请先填写 GitHub 仓库链接", "error");
    setBusy(true);
    toast("正在下载并安装，请稍候…");
    try {
      const result = await api.post("templates/install", { url, name: nameInput.value.trim() });
      reportInstalled(result);
      urlInput.value = "";
      nameInput.value = "";
      load();
    } catch (e) {
      toast(`安装失败：${e.message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function uploadZip() {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    setBusy(true);
    try {
      reportInstalled(await api.upload("templates/upload", file));
      load();
    } catch (e) {
      toast(`安装失败：${e.message}`, "error");
    } finally {
      setBusy(false);
    }
  }

  async function preview(tpl) {
    toast(`正在用示例数据渲染「${tpl.display_name}」…`);
    try {
      const data = await api.get(`templates/${seg(tpl.name)}/preview`);
      showHtmlViewer(`模板预览：${tpl.display_name}（示例数据）`, data.html);
    } catch (e) {
      toast(`预览失败：${e.message}`, "error");
    }
  }

  async function setDefault(tpl) {
    try {
      await api.post("templates/default", { name: tpl.name });
      toast(`已设为默认模板：${tpl.display_name}`, "success");
      load();
    } catch (e) {
      toast(`设置失败：${e.message}`, "error");
    }
  }

  async function uninstall(tpl, isCurrent) {
    const tip = isCurrent ? "它是当前使用的模板，卸载后会自动改回 HatsuneMiku。" : "";
    const ok = await confirmDialog(`确定卸载模板「${tpl.display_name}」吗？${tip}`, "卸载");
    if (!ok) return;
    try {
      const result = await api.post(`templates/${seg(tpl.name)}/uninstall`);
      toast(result.reverted_to ? `已卸载，默认模板已改回 ${result.reverted_to}` : "已卸载", "success");
      load();
    } catch (e) {
      toast(`卸载失败：${e.message}`, "error");
    }
  }

  function card(tpl, current) {
    const isCurrent = tpl.name === current;
    const tag = tpl.tag ? el("span", { class: "badge", text: tpl.tag }) : null;
    // 非法颜色值会被浏览器忽略
    if (tag && tpl.tag_color) tag.style.color = tpl.tag_color;
    return el("div", { class: isCurrent ? "tpl-card current" : "tpl-card" }, [
      el("div", { class: "title", text: tpl.display_name }),
      el("div", {}, [
        isCurrent ? el("span", { class: "badge success", text: "当前使用" }) : null,
        el("span", { class: tpl.builtin ? "badge gray" : "badge warning", text: tpl.builtin ? "内置" : "自定义" }),
        tag,
      ]),
      el("div", { class: "desc", text: tpl.desc || (tpl.display_name !== tpl.name ? tpl.name : "") }),
      tpl.install_info && tpl.install_info.installed_at
        ? el("div", { class: "muted", style: "font-size:12px", text: `安装于 ${tpl.install_info.installed_at}` })
        : null,
      el("div", { class: "actions" }, [
        el("button", { class: "btn small", text: "预览", onclick: () => preview(tpl) }),
        isCurrent ? null : el("button", { class: "btn small", text: "设为默认", onclick: () => setDefault(tpl) }),
        tpl.removable ? el("button", { class: "btn small danger", text: "卸载", onclick: () => uninstall(tpl, isCurrent) }) : null,
      ]),
    ]);
  }

  async function load() {
    try {
      const data = await api.get("templates");
      currentInfo.textContent = `当前使用：${data.current}`;
      grid.replaceChildren(...data.templates.map((t) => card(t, data.current)));
    } catch (e) {
      grid.replaceChildren(el("div", { class: "empty", text: `加载失败：${e.message}` }));
    }
  }

  return { activate: load, deactivate() {} };
}
