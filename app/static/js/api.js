/*
  サーバとのやりとり。トークンを付け、断りを1つの形(ApiError)にそろえる。
  文言はサーバが持つ。ここでは作らない。
*/
const TOKEN = document.querySelector('meta[name="tool-token"]').content;

export class ApiError extends Error {
  constructor(status, code, message, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body || {};
  }
}

// このタブの印。ログの「それまでの経過」を同じタブで拾うため(2枚開いても混ざらない)
function tabId() {
  try {
    let id = sessionStorage.getItem("filelist-tab");
    if (!id) {
      id = Math.random().toString(36).slice(2, 10);
      sessionStorage.setItem("filelist-tab", id);
    }
    return id;
  } catch (e) {
    return "";
  }
}
const TAB = tabId();

async function call(method, path, body) {
  const init = { method, headers: { "X-Tool-Token": TOKEN, "X-Tab": TAB,
                                    "X-Screen": location.pathname } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new ApiError(0, "offline", "アプリに接続できません。終了したか、止まっています。");
  }
  let data = {};
  try { data = await res.json(); } catch (e) { data = {}; }
  if (!res.ok) {
    const err = data.error || {};
    throw new ApiError(res.status, err.code || "http_" + res.status,
      err.message || `うまくいきませんでした(${res.status})。`, data);
  }
  return data;
}

export const get = (path) => call("GET", path);
export const post = (path, body) => call("POST", path, body || {});
export const token = () => TOKEN;

/** 失敗しても投げない送り口(画面のエラーを届けるときに使う。送ることでまたエラーにしない) */
export async function quietPost(path, body) {
  try {
    return await call("POST", path, body || {});
  } catch (e) {
    return null;
  }
}
