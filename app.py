#!/usr/bin/env python3
"""Французский A1+: маленький тренажёр-чат.

Один файл, без базы: история держится в памяти по cookie.
Модель — DeepSeek через OpenAI-совместимый API (ключ из /root/.hermes/.env).
"""
import json
import os
import re
import secrets
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.parse

PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")
MODEL = os.environ.get("MODEL", "deepseek-chat")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1")

KEY = os.environ.get("OPENAI_API_KEY", "")
if not KEY:
    envfile = os.environ.get("ENV_FILE", "")
    if envfile and os.path.exists(envfile):
        for line in open(envfile):
            if line.startswith("DEEPSEEK_API_KEY="):
                KEY = line.split("=", 1)[1].strip()
                break

SYSTEM = (
    "Ты добрый учитель французского для новичка (уровень A1). Строгие правила:\n"
    "1) Пиши по-французски ОЧЕНЬ просто: короткие фразы, не больше 8 слов, только présent и самые базовые слова.\n"
    "2) После каждой французской фразы в скобках дай русский перевод.\n"
    "3) Если ученик ошибся — мягко исправь: сначала «Mieux: …» с правильным вариантом, потом продолжай.\n"
    "4) В конце задай ОДИН простой вопрос по-французски (с переводом).\n"
    "5) Никаких длинных объяснений грамматики, максимум одна короткая подсказка.\n"
    "6) Темы: приветствие, знакомство, кафе, магазин, числа, время, семья, хобби, погода.\n"
    "7) Если ученик пишет по-русски — ответь по-французски и переведи, не читай лекций."
)

SESSIONS = {}  # sid -> {"msgs": [...], "ts": float}
SID_TTL = 6 * 3600

CSS = """
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:#fdf7ef;color:#2b2118;
 font-family:-apple-system,BlinkMacSystemFont,'SF Pro Rounded','Segoe UI',Roboto,sans-serif}
body{padding:calc(env(safe-area-inset-top,0px) + 14px) 0 calc(20px + env(safe-area-inset-bottom))}
.wrap{max-width:520px;margin:0 auto;padding:0 16px}
head,header{display:block}
.top{display:flex;align-items:center;gap:10px;margin-bottom:4px}
.flag{width:38px;height:38px;border-radius:12px;background:linear-gradient(90deg,#0055a4 33%,#fff 33% 66%,#ef4135 66%);
 box-shadow:0 2px 8px rgba(0,0,0,.12);flex:none}
h1{font-size:19px;margin:0;letter-spacing:-.2px}
.sub{font-size:12px;color:#9c8f80;margin:2px 0 14px}
.lvl{display:inline-block;background:#fff;border:1px solid #f0e3d2;color:#b07d3a;font-size:11px;
 font-weight:700;padding:3px 8px;border-radius:7px;margin-left:6px}
.chips{display:flex;gap:7px;overflow-x:auto;padding-bottom:12px}
.chips a{flex:none;text-decoration:none;background:#fff;border:1px solid #f0e3d2;color:#6b5a49;
 font-size:12.5px;font-weight:600;padding:9px 13px;border-radius:11px}
.msg{margin-bottom:10px;display:flex}
.msg .b{max-width:88%;padding:11px 14px;border-radius:16px;font-size:14.5px;line-height:1.5;white-space:pre-wrap}
.msg.t .b{background:#fff;border:1px solid #f0e3d2;border-bottom-left-radius:5px}
.msg.m{justify-content:flex-end}
.msg.m .b{background:#2b2118;color:#fdf7ef;border-bottom-right-radius:5px}
.hint{background:#fff7e8;border:1px dashed #e8cfa6;border-radius:12px;padding:11px 13px;font-size:12.5px;
 color:#8a7047;margin-bottom:14px;line-height:1.45}
form{display:flex;gap:8px;position:sticky;bottom:calc(8px + env(safe-area-inset-bottom));
 background:#fdf7ef;padding-top:8px}
input[type=text]{flex:1;border:1px solid #f0e3d2;border-radius:14px;padding:14px 15px;font-size:15px;
 background:#fff;font-family:inherit;color:#2b2118}
input[type=text]:focus{outline:2px solid #e8cfa6}
button{border:0;border-radius:14px;padding:14px 18px;background:#2b2118;color:#fdf7ef;font-weight:700;
 font-size:14px;font-family:inherit}
button.ghost{background:#fff;border:1px solid #f0e3d2;color:#6b5a49;padding:8px 12px;font-size:12px;font-weight:600}
.foot{color:#b3a595;font-size:11px;text-align:center;margin-top:14px}
.typing{color:#9c8f80;font-size:13px;padding:4px 2px 10px}
"""

TOPICS = [("Приветствие", "Bonjour ! Comment tu t'appelles ?"),
          ("В кафе", "Je voudrais un café, s'il vous plaît."),
          ("Числа", "Combien ça coûte ?"),
          ("Семья", "J'ai une sœur et un frère."),
          ("Погода", "Il fait beau aujourd'hui.")]


def ask_llm(msgs):
    payload = {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}] + msgs,
               "temperature": 0.7, "max_tokens": 400}
    req = urllib.request.Request(BASE_URL.rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {KEY}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["choices"][0]["message"]["content"].strip()


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def page(sid, msgs, thinking=False):
    body = ""
    if not msgs:
        body += ('<div class="hint">Начни с «Bonjour» или нажми подсказку выше. '
                 'Я отвечаю по-французски и сразу перевожу.</div>')
    for m in msgs[-40:]:
        cls = "m" if m["role"] == "user" else "t"
        body += f'<div class="msg {cls}"><div class="b">{esc(m["content"])}</div></div>'
    if thinking:
        body += '<div class="typing">… отвечаю</div>'
    chips = "".join(f'<a href="?say={urllib.parse.quote(t[1])}">{esc(t[0])}</a>' for t in TOPICS)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Français A1</title><meta name="theme-color" content="#fdf7ef">
<style>{CSS}</style></head><body><div class="wrap">
<div class="top"><div class="flag"></div><div><h1>Français<span class="lvl">A1+</span></h1>
<div class="sub">тренажёр разговорного · короткие фразы с переводом</div></div></div>
<div class="chips">{chips}</div>
{body}
<form method="post" action="say">
<input type="text" name="text" placeholder="Напиши по-французски или по-русски…" autofocus autocomplete="off">
<button>→</button></form>
<div class="foot"><a href="?reset=1" style="color:#b3a595;text-decoration:none">начать заново</a></div>
</div></body></html>"""


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b)

    def _sid(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            if part.strip().startswith("fsid="):
                return part.split("=", 1)[1].strip()
        sid = secrets.token_urlsafe(12)
        self._new = sid
        return sid

    def _sess(self, sid):
        now = time.time()
        for k in [k for k, v in SESSIONS.items() if now - v["ts"] > SID_TTL]:
            SESSIONS.pop(k, None)
        s = SESSIONS.setdefault(sid, {"msgs": [], "ts": now})
        s["ts"] = now
        return s

    def _reply(self, sid, extra=None):
        s = self._sess(sid)
        e = dict(extra or {})
        if getattr(self, "_new", None):
            e["Set-Cookie"] = f"fsid={self._new}; Path=/; Max-Age=86400"
        self._send(200, page(sid, s["msgs"]), extra=e)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        sid = self._sid()
        s = self._sess(sid)
        if (q.get("reset") or [""])[0] == "1":
            s["msgs"] = []
            self._reply(sid)
            return
        if (q.get("say") or [None])[0]:
            text = q["say"][0]
            self._turn(sid, text)
            return
        self._reply(sid)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        text = (form.get("text") or [""])[0].strip()
        sid = self._sid()
        if not text:
            self._reply(sid)
            return
        self._turn(sid, text)

    def _turn(self, sid, text):
        s = self._sess(sid)
        s["msgs"].append({"role": "user", "content": text})
        try:
            answer = ask_llm([{"role": m["role"], "content": m["content"]} for m in s["msgs"][-12:]])
        except Exception as e:
            answer = f"Сеть подвела ({type(e).__name__}). Попробуй ещё раз."
        s["msgs"].append({"role": "assistant", "content": answer})
        s["msgs"] = s["msgs"][-30:]
        self._reply(sid)


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
