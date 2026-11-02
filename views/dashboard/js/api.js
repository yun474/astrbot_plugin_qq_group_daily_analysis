// 后端接口封装：所有请求都通过 AstrBot 注入的 bridge 转发
const bridge = window.AstrBotPluginView;

export const ready = () => bridge.ready();
export const onContext = (handler) => bridge.onContext(handler);

export const api = {
  get: (endpoint, params) => bridge.apiGet(endpoint, params),
  post: (endpoint, body) => bridge.apiPost(endpoint, body || {}),
  upload: (endpoint, file) => bridge.upload(endpoint, file),
  download: (endpoint, params, filename) => bridge.download(endpoint, params, filename),
};

/** 路径参数转义（模板名、报告 ID 等） */
export const seg = (value) => encodeURIComponent(value);
