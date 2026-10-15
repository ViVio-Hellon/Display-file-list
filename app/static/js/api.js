/*
  サーバとのやりとり。トークンを付け、断りを1つの形(ApiError)にそろえる。
  文言はサーバが持つ。ここでは作らない。
*/
const TOKEN = document.querySelector('meta[name="tool-token"]').content;

export class ApiError extends Error {
  constructor(status, code, message, body) {
    super(message);
    this.status = status;
    this.code = code;
    this.body = body || {};
  }
}

async function call(method, path, body) {
  const init = { method, headers: { "X-Tool-Token": TOKEN } };
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
