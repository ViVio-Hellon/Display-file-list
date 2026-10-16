"""出来事の記録の決まり ── **あとから「なぜ」を辿れる形に残す**(純粋な層)

日報管理ツール(ViVio-Hellon/vba-daily-report-python-migration v4.1.0)の
`nippou/logic/event_log.py` を、このツールの画面と操作に合わせて写したもの。

【何を残すか ── なぜなぜの段に合わせる】

    起きたこと      … いつ・どの端末・どの画面・何をした(操作)・何と出た
    直接の原因      … 例外の種類と文・**コードのどこで**(ファイル:行)
    そのときの状態  … 開いていたフォルダ・版
    それまでの経過  … 同じタブで、その前に何をしていたか(操作の並び)
    送った中身      … 打った値(空欄は省く。合言葉などは *** に伏せる)

1件ずつに**番号**を付けます(`E1016-0912-7KX`)。画面のエラーにも同じ番号を
出すので、「この番号のエラーが出た」と言ってもらえば記録の1件に辿れます。

【この層の約束】
ファイルも時計も触りません。記録の形・入力の要約・番号の作り方・経過の拾い方・
なぜなぜシートの組み立てだけを持ちます。書く・読むのは `event_log.py`。
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional, Sequence

# ------------------------------------------------------------------
# 種類 ── 一覧で絞り込む単位。文言から推し量らない
# ------------------------------------------------------------------
KIND_ERROR = "error"       # 予期しないエラー(サーバ)。番号を画面に出す
KIND_CLIENT = "client"     # 画面(ブラウザ)のエラー
KIND_WARN = "warn"         # 記録に残った警告(読めない・書けない など)
KIND_REFUSED = "refused"   # 業務としての断り(4xx)。なぜできなかったか
KIND_OP = "op"             # 操作(押した・開いた)。経過を辿るためのもの
KIND_INFO = "info"         # 起動・設定の変更・リネームの結果など

KIND_LABELS = {
    KIND_ERROR: "エラー",
    KIND_CLIENT: "画面のエラー",
    KIND_WARN: "警告",
    KIND_REFUSED: "断り",
    KIND_OP: "操作",
    KIND_INFO: "記録",
}

#: 番号の頭の1文字。読み上げても取り違えないように種類で分ける
_PREFIX = {KIND_ERROR: "E", KIND_CLIENT: "C", KIND_WARN: "W",
           KIND_REFUSED: "R", KIND_OP: "O", KIND_INFO: "I"}

#: 番号の末尾に使う文字。0/O・1/I/L・5/S・8/B のように見間違えるものを除く
_ALPHABET = "234679ACDEFGHJKMNPQRTUVWXYZ"

SCOPES = {
    "errors": (KIND_ERROR, KIND_CLIENT),
    "problems": (KIND_ERROR, KIND_CLIENT, KIND_WARN, KIND_REFUSED),
    "all": tuple(KIND_LABELS),
}
SCOPE_LABELS = {"errors": "エラーだけ", "problems": "エラー・警告・断り", "all": "操作も全部"}
DEFAULT_SCOPE = "errors"

STATUS_OPEN = "open"
STATUS_DOING = "doing"
STATUS_DONE = "done"
STATUS_LABELS = {STATUS_OPEN: "未着手", STATUS_DOING: "対策中", STATUS_DONE: "対策済"}

WHY_COUNT = 5
NOTE_MAX = 400

SECRET_WORDS = ("password", "passwd", "token", "secret", "合言葉", "パスワード")
INPUT_MAX_ITEMS = 40
INPUT_MAX_LEN = 200            # フォルダのパスは長いので、日報(80)より長く残す
MESSAGE_MAX = 500
TRACE_MAX = 8000


# ------------------------------------------------------------------
# 番号
# ------------------------------------------------------------------
def new_id(kind: str, now: datetime, rng: Optional[random.Random] = None) -> str:
    """``E1016-0912-7KX``(種類・月日・時分・3文字)。日時が入るので番号だけで「いつ」が分かる。"""
    pick = (rng or random).choice
    tail = "".join(pick(_ALPHABET) for _ in range(3))
    return f"{_PREFIX.get(kind, 'X')}{now:%m%d}-{now:%H%M}-{tail}"


def kind_of_status(status: int) -> str:
    if status >= 500:
        return KIND_ERROR
    if status >= 400:
        return KIND_REFUSED
    return KIND_OP


# ------------------------------------------------------------------
# 入力の要約
# ------------------------------------------------------------------
def is_secret(key: str) -> bool:
    low = str(key).lower()
    return any(word in low for word in SECRET_WORDS)


def summarize_input(data: Any, *, max_items: int = INPUT_MAX_ITEMS,
                    max_len: int = INPUT_MAX_LEN) -> dict:
    """送られた中身を「鍵の道: 値」の平たい形に。空欄は残さない。伏せる鍵は ***。"""
    out: dict = {}
    overflow = 0

    def put(path: str, value: Any) -> None:
        nonlocal overflow
        if len(out) >= max_items:
            overflow += 1
            return
        text = " ".join(str(value).split())
        if len(text) > max_len:
            text = text[:max_len] + "…"
        out[path] = text

    def walk(value: Any, path: str, depth: int) -> None:
        if path and is_secret(path.rsplit(".", 1)[-1]):
            if value not in (None, ""):
                put(path, "***")
            return
        if isinstance(value, dict):
            if depth >= 4:
                put(path, f"({len(value)}項目)")
                return
            for key, inner in value.items():
                walk(inner, f"{path}.{key}" if path else str(key), depth + 1)
            return
        if isinstance(value, (list, tuple)):
            if not value:
                return
            if depth >= 4 or len(value) > 12:
                put(path, f"({len(value)}件)")
                return
            for i, inner in enumerate(value):
                walk(inner, f"{path}[{i}]", depth + 1)
            return
        if value is None or (isinstance(value, str) and not value.strip()):
            return
        put(path or "値", value)

    walk(data, "", 0)
    if overflow:
        out["…"] = f"ほか {overflow} 項目"
    return out


def clip(text: Any, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "…"


# ------------------------------------------------------------------
# コードのどこで起きたか
# ------------------------------------------------------------------
def where_in_code(frames: Sequence[tuple], roots: Sequence[str]) -> str:
    """例外の通り道から、**このツールのコードの中でいちばん深い所**を1つ。"""
    def norm(path: str) -> str:
        return str(path).replace("\\", "/")

    keys = [norm(r).rstrip("/") + "/" for r in roots if r]
    ours = [(f, n, fn) for f, n, fn in frames
            if any(norm(f).startswith(k) for k in keys) and "/site-packages/" not in norm(f)]
    pick = ours[-1] if ours else (frames[-1] if frames else None)
    if pick is None:
        return ""
    path, line, func = pick
    shown = norm(path)
    for key in keys:
        if shown.startswith(key):
            shown = shown[len(key):]
            break
    return f"{shown}:{line} ({func})"


# ------------------------------------------------------------------
# 操作の呼び名 ── 経過を人が読める言葉で並べる
# ------------------------------------------------------------------
ACTION_LABELS = {
    ("GET", "/"): "画面を開いた",
    ("GET", "/logs"): "ログを開いた",
    ("GET", "/print"): "PDF作成 / 印刷を開いた",
    ("GET", "/api/filelist"): "ファイル名取得",
    ("POST", "/api/rename/preview"): "ファイル名変換: 変わる名前を見る",
    ("POST", "/api/rename/run"): "ファイル名変換: この内容で直す",
    ("POST", "/api/shutdown"): "終了",
    ("POST", "/api/log/settings"): "ログの出力先を変える",
    ("POST", "/api/log/client"): "画面のエラーを知らせた",
    ("POST", "/api/log/"): "ログの操作",
}

#: 開いた画面として**ちょうど**その道のときだけ当てるもの(頭で当てると `/` がすべてに当たる)
_EXACT = ("/", "/logs", "/print")


def label_of(method: str, path: str) -> str:
    method = (method or "").upper()
    best, label = "", ""
    for (m, head), text in ACTION_LABELS.items():
        if m != method:
            continue
        hit = path == head if head in _EXACT else path.startswith(head)
        if hit and len(head) > len(best):
            best, label = head, text
    return label or f"{method} {path}".strip()


# ------------------------------------------------------------------
# どの要求を残すか
# ------------------------------------------------------------------
#: 残さない道(心拍・見張り)。断りやエラーなら残す
QUIET_PATHS = frozenset({"/api/health", "/api/alive", "/api/bye", "/api/state",
                         "/api/log/client", "/favicon.ico"})
_FILE_PREFIXES = ("/static/",)
_QUIET_PREFIXES = ("/api/log/",)       # ログを見る操作そのものは経過に要らない
#: 読むだけの問い合わせ(GET /api/…)は残さないが、**これは業務の操作**なので残す
RECORDED_GET_APIS = frozenset({"/api/filelist"})


def should_record(method: str, path: str, status: int, *, quiet: bool = False) -> bool:
    """残す: 押した操作(POST)・開いた画面・ファイル名取得・**断りとエラーは全部**。
    残さない: 心拍・見張り・読むだけの問い合わせ・静的ファイル・ログの面の操作。"""
    method = method.upper()
    if status >= 400:
        return not (status == 404 and path == "/favicon.ico")
    if path == "/api/log/settings" and method == "POST":
        return True                      # 出力先を変えたことは残す
    if (path.startswith(_FILE_PREFIXES) or path.startswith(_QUIET_PREFIXES)
            or path in QUIET_PATHS or quiet):
        return False
    if method == "GET" and path.startswith("/api/"):
        return path in RECORDED_GET_APIS
    return method in ("GET", "POST")


# ------------------------------------------------------------------
# 1件の形
# ------------------------------------------------------------------
#: 記録の欄。**この順でCSVにも出す**
FIELDS = ("id", "at", "kind", "terminal", "screen", "action", "label", "status",
          "message", "cause", "where", "folder", "tab", "request", "ms", "logger",
          "version", "input", "crumbs", "trace", "count")


def make(kind: str, *, at: datetime, id: str = "", **fields: Any) -> dict:
    """出来事1件。欄が欠けていても読めるよう、空で埋める。"""
    record: dict = {name: "" for name in FIELDS}
    record.update({"id": id or new_id(kind, at),
                   "at": at.isoformat(timespec="milliseconds"), "kind": kind})
    for name, value in fields.items():
        if name in record and value is not None:
            record[name] = value
    if not record["label"] and record["action"]:
        method, _, path = str(record["action"]).partition(" ")
        record["label"] = label_of(method, path)
    if not record["folder"] and isinstance(record["input"], dict):
        record["folder"] = record["input"].get("folder", "")
    record["message"] = clip(record["message"], MESSAGE_MAX)
    record["trace"] = clip(record["trace"], TRACE_MAX)
    return record


def parse_at(text: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------
# 絞り込み・経過
# ------------------------------------------------------------------
def select(records: Iterable[dict], *, scope: str = DEFAULT_SCOPE,
           terminal: str = "", text: str = "", limit: int = 500) -> list:
    """一覧に出すもの。新しい順。"""
    kinds = SCOPES.get(scope, SCOPES[DEFAULT_SCOPE])
    needle = (text or "").strip().lower()
    out = []
    for rec in records:
        if rec.get("kind") not in kinds:
            continue
        if terminal and rec.get("terminal") != terminal:
            continue
        if needle and needle not in " ".join(
                str(rec.get(k, "")) for k in ("id", "message", "cause", "label",
                                             "action", "folder", "screen", "where")).lower():
            continue
        out.append(rec)
    out.sort(key=lambda r: str(r.get("at", "")), reverse=True)
    return out[:limit]


def timeline(records: Iterable[dict], target: dict, *, before_minutes: int = 30,
             before_limit: int = 30, after_minutes: int = 5, after_limit: int = 5) -> list:
    """それまでの経過。同じ端末の前30分(最大30件)と後5分。同じタブがあればタブで絞る。"""
    at = parse_at(target.get("at", ""))
    if at is None:
        return [target]
    start = at - timedelta(minutes=before_minutes)
    end = at + timedelta(minutes=after_minutes)
    tab = target.get("tab") or ""
    terminal = target.get("terminal") or ""
    before, after = [], []
    for rec in records:
        if rec.get("id") == target.get("id"):
            continue
        if terminal and rec.get("terminal") not in ("", terminal):
            continue
        if tab and rec.get("tab") and rec.get("tab") != tab:
            continue
        when = parse_at(rec.get("at", ""))
        if when is None or when < start or when > end:
            continue
        (before if when <= at else after).append((when, rec))
    before.sort(key=lambda p: p[0])
    after.sort(key=lambda p: p[0])
    return [r for _, r in before[-before_limit:]] + [target] + [r for _, r in after[:after_limit]]


# ------------------------------------------------------------------
# なぜなぜシート
# ------------------------------------------------------------------
def clean_note(text: Any) -> str:
    return str(text or "").strip()[:NOTE_MAX]


def clean_analysis(body: dict) -> dict:
    whys = [clean_note(w) for w in list(body.get("whys") or [])[:WHY_COUNT]]
    whys += [""] * (WHY_COUNT - len(whys))
    status = body.get("status") if body.get("status") in STATUS_LABELS else STATUS_OPEN
    return {"whys": whys, "measure": clean_note(body.get("measure")),
            "status": status, "by": clean_note(body.get("by"))[:40]}


#: 予期しないエラーで画面に出す決まり文句の目印。中身を言っていないので、一覧では例外を出す
GENERIC_MARK = "エラー番号"


def is_generic(message: str) -> bool:
    return GENERIC_MARK in str(message or "")


def headline(rec: dict) -> str:
    message = str(rec.get("message") or "")
    if is_generic(message) and rec.get("cause"):
        return str(rec["cause"])
    return message or str(rec.get("cause") or "")


def step_text(rec: dict) -> str:
    """経過の1行。``09:12:01 ファイル名取得 → 断り: 指定のフォルダは存在しません。``"""
    at = parse_at(rec.get("at", ""))
    when = at.strftime("%H:%M:%S") if at else ""
    what = rec.get("label") or rec.get("action") or KIND_LABELS.get(rec.get("kind"), "")
    kind = rec.get("kind")
    if kind == KIND_OP:
        tail = ""
    elif rec.get("message") or rec.get("cause"):
        tail = f" → {KIND_LABELS.get(kind, kind)}: {clip(headline(rec), 160)}"
    else:
        tail = f" → {KIND_LABELS.get(kind, kind)}"
    if kind in (KIND_WARN, KIND_INFO) and not rec.get("label"):
        what = rec.get("message", "")
        tail = f" ({KIND_LABELS.get(kind, kind)})"
    return f"{when} {what}{tail}".strip()


def why_hint(rec: dict) -> str:
    """なぜ1の手がかり(書くのは人)。記録から言えることだけを並べる。"""
    parts = []
    label = rec.get("label") or rec.get("action")
    if label:
        parts.append(f"「{label}」の途中で")
    message = rec.get("message")
    if message and not is_generic(message):
        parts.append(f"「{clip(message, 80)}」と出た。")
    if rec.get("cause"):
        parts.append(f"直接には {clip(rec['cause'], 120)}")
    if rec.get("where"):
        parts.append(f"(コードの {rec['where']})")
    return " ".join(parts)


def sheet(target: dict, steps: Sequence[dict], analysis: Optional[dict] = None) -> dict:
    """なぜなぜシート1枚。**記録から言えること**と**人が書くこと**を分けて持つ。"""
    at = parse_at(target.get("at", ""))
    facts = [
        ("番号", target.get("id", "")),
        ("いつ", at.strftime("%Y/%m/%d %H:%M:%S") if at else target.get("at", "")),
        ("種類", KIND_LABELS.get(target.get("kind"), target.get("kind", ""))),
        ("どの端末", target.get("terminal", "")),
        ("どの画面", target.get("screen", "")),
        ("何をした", target.get("label") or target.get("action", "")),
        ("何と出た", target.get("message", "")),
    ]
    cause = [("例外", target.get("cause", "")), ("コードの場所", target.get("where", "")),
             ("記録した所", target.get("logger", "")), ("応答", str(target.get("status") or ""))]
    state = [("フォルダ", target.get("folder", "")), ("版", target.get("version", ""))]
    note = analysis or {}
    return {
        "id": target.get("id", ""),
        "facts": [{"label": k, "value": str(v)} for k, v in facts if v],
        "cause": [{"label": k, "value": str(v)} for k, v in cause if v],
        "state": [{"label": k, "value": str(v)} for k, v in state if v],
        "input": target.get("input") or {},
        "crumbs": target.get("crumbs") or [],
        "trace": target.get("trace", ""),
        "steps": [{"id": r.get("id", ""), "text": step_text(r), "kind": r.get("kind", ""),
                   "is_target": r.get("id") == target.get("id")} for r in steps],
        "hint": why_hint(target),
        "analysis": {
            "whys": list(note.get("whys") or [""] * WHY_COUNT),
            "measure": note.get("measure", ""),
            "status": note.get("status", STATUS_OPEN),
            "status_label": STATUS_LABELS.get(note.get("status", STATUS_OPEN), ""),
            "by": note.get("by", ""),
            "at": note.get("at", ""),
            "terminal": note.get("terminal", ""),
        },
    }


# ------------------------------------------------------------------
# CSV・一覧の1行
# ------------------------------------------------------------------
CSV_HEADER = ("番号", "日時", "種類", "端末", "画面", "操作", "応答", "何と出た",
              "例外", "コードの場所", "フォルダ", "版", "送った中身",
              *(f"なぜ{i}" for i in range(1, WHY_COUNT + 1)),
              "対策", "状態", "書いた人", "書いた日時")


def csv_row(rec: dict, analysis: Optional[dict] = None) -> list:
    note = analysis or {}
    whys = list(note.get("whys") or [])
    whys += [""] * (WHY_COUNT - len(whys))
    at = parse_at(rec.get("at", ""))
    sent = "; ".join(f"{k}={v}" for k, v in (rec.get("input") or {}).items())
    return [rec.get("id", ""),
            at.strftime("%Y/%m/%d %H:%M:%S") if at else str(rec.get("at", "")),
            KIND_LABELS.get(rec.get("kind"), str(rec.get("kind", ""))),
            rec.get("terminal", ""), rec.get("screen", ""),
            rec.get("label") or rec.get("action", ""),
            str(rec.get("status") or ""), rec.get("message", ""),
            rec.get("cause", ""), rec.get("where", ""), rec.get("folder", ""),
            rec.get("version", ""), sent, *whys[:WHY_COUNT],
            note.get("measure", ""),
            STATUS_LABELS.get(note.get("status", ""), "") if note else "",
            note.get("by", ""), note.get("at", "")]


def list_row(rec: dict, analysis: Optional[dict] = None) -> dict:
    """一覧の1行。画面はこれを写すだけ。"""
    at = parse_at(rec.get("at", ""))
    note = analysis or {}
    return {"id": rec.get("id", ""),
            "at": at.strftime("%m/%d %H:%M:%S") if at else str(rec.get("at", "")),
            "kind": rec.get("kind", ""),
            "kind_label": KIND_LABELS.get(rec.get("kind"), ""),
            "terminal": rec.get("terminal", ""),
            "screen": rec.get("screen", ""),
            "label": rec.get("label") or rec.get("action", ""),
            "message": clip(headline(rec), 160),
            "count": rec.get("count") or "",
            "status": note.get("status", "") if note else "",
            "status_label": STATUS_LABELS.get(note.get("status", ""), "") if note else ""}
