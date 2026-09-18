# -*- coding: utf-8 -*-
"""One patient translator for the whole repo: UI strings + README + 32 book files, zh -> en/km.

- Engine: Google gtx POST. Self-throttling: starts at 3.5s/request, speeds up to 0.8s
  while healthy, backs off 2x on 429 up to a 15-minute SNOOZE, then retries forever
  (up to N snoozes). Never loses finished work: every file is written whole as it
  completes, and a resume state file skips done items.
- Structure-safe: `### N.` entry markers, `<!-- 成本标签 -->` tags, headings numbers,
  Source lines (citations) and URLs never go through the translator.
Usage: python tools/i18n_all.py            (resumes)
       python tools/i18n_all.py --force
"""
import os, re, sys, json, time, urllib.request, urllib.parse, urllib.error

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BASE, "tools", "i18n_progress.json")
LOG = open(os.path.join(BASE, "tools", "i18n_all.log"), "a", encoding="utf-8")

def log(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True); LOG.write(line + "\n"); LOG.flush()

FIELD_RE = re.compile(r"^- (成本|说人话|收益|证据等级|来源|备注)：(.*)$")
HLABEL = {"成本": "Cost", "说人话": "Plain words", "收益": "Benefit",
          "证据等级": "Evidence", "来源": "Source", "备注": "Note"}

# ---------------- network ----------------
_g_state = {"pace": float(os.environ.get("I18N_PACE", "3.5")),
            "ok_streak": 0,
            "snooze_left": int(os.environ.get("I18N_SNOOZES", "40"))}

def _gtx_raw(part, to):
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=" + to + "&dt=t"
    data = urllib.parse.urlencode({"q": part}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    r = json.loads(urllib.request.urlopen(req, timeout=45).read().decode())
    return "".join(s[0] for s in r[0] if s and s[0] is not None)

def engine(text, to):
    """Translate <=1600 chars. On 429 snooze long; keep trying."""
    attempts = 0
    while attempts < 30:
        time.sleep(_g_state["pace"])
        try:
            out = _gtx_raw(text, to)
            _g_state["ok_streak"] += 1
            if _g_state["ok_streak"] > 5 and _g_state["pace"] > 0.8:
                _g_state["pace"] = max(0.8, _g_state["pace"] * 0.95)
            return out
        except urllib.error.HTTPError as e:
            _g_state["ok_streak"] = 0
            if e.code == 429:
                snooze = min(900, max(60, _g_state["pace"] * 20))
                log(f"429 -> snooze {snooze}s (left {_g_state['snooze_left']})")
                _g_state["pace"] = min(8.0, _g_state["pace"] * 2)
                _g_state["snooze_left"] -= 1
                if _g_state["snooze_left"] < 0: raise
                time.sleep(snooze)
                continue
            if e.code in (400, 403) and len(text) > 500:
                # split and retry halves
                mid = text.rfind("\n", 0, len(text) // 2)
                if mid > 0:
                    return engine(text[:mid], to) + "\n" + engine(text[mid + 1:], to)
            time.sleep(5)
        except Exception as e:
            log(f"net err {e} -> sleep 20")
            time.sleep(20)
    raise RuntimeError("engine gave up")

def translate_lines(payload, to):
    """payload: list of Chinese strings. Returns same-length list translated,
    batching for speed and re-batching on line drift."""
    out = []
    buf, bufi = [], []
    def flush():
        if not buf: return
        got = engine("\n".join(buf), to).split("\n")
        if len(got) == len(buf):
            out.extend(g.strip() for g in got)
        else:   # drift -> one by one
            for b in buf:
                out.append(engine(b, to).replace("\n", " ").strip())
    for s in payload:
        if len("\n".join(buf + [s])) > 1400:
            flush(); buf = []
        buf.append(s)
    flush()
    return out

# ---------------- book file translation ----------------
def translate_book(text, lang):
    lines = text.split("\n")
    idxs, payload = [], []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith("<!--") or s.startswith("[← 回总目录]"):
            continue
        mf = FIELD_RE.match(s)
        if mf and mf.group(1) in ("来源", "证据等级"):
            continue
        if mf:
            idxs.append((i, "field", mf.group(1))); payload.append(mf.group(2)); continue
        mh = re.match(r"^(#{1,4} )(\d+\. )?(.*)$", ln)
        if mh and mh.group(3).strip():
            idxs.append((i, "head", mh)); payload.append(mh.group(3).strip()); continue
        idxs.append((i, "body", None)); payload.append(s)
    got = translate_lines(payload, lang)
    out = lines[:]
    for (i, kind, aux), tr in zip(idxs, got):
        lead = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        if kind == "field":
            out[i] = f"{lead}- {HLABEL[aux]}: {tr}"
        elif kind == "head":
            out[i] = f"{aux.group(1)}{(aux.group(2) or '')}{tr}"
        else:
            out[i] = lead + tr
    result = "\n".join(out)
    result = result.replace("- 证据等级：", "- Evidence: ").replace("- 来源：", "- Source: ")
    return result

def sha(path):
    import hashlib
    return hashlib.md5(open(path, "rb").read()).hexdigest()[:10]

def run(langs):
    state = {}
    if os.path.exists(STATE):
        try: state = json.load(open(STATE, encoding="utf-8"))
        except Exception: state = {}
    def done(key, srcpath):
        return state.get(key) == sha(srcpath) and not FORCE
    def mark(key, srcpath):
        state[key] = sha(srcpath)
        json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)

    readme_src = os.path.join(BASE, "README.md")
    files = sorted(f for f in os.listdir(os.path.join(BASE, "book")) if f.endswith(".md"))
    t00 = time.time()
    for lang in langs:
        # UI strings
        uitgt = os.path.join(BASE, "tools", "ui_i18n.json")
        ui = json.load(open(uitgt, encoding="utf-8")) if os.path.exists(uitgt) else {}
        from i18n_ui_strings import STR
        need = [k for k in STR if k not in ui.get(lang, {})]
        if need:
            vals = translate_lines([STR[k] for k in need], lang)
            ui.setdefault(lang, {})
            for k, v in zip(need, vals): ui[lang][k] = v
            json.dump(ui, open(uitgt, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            log(f"ui.{lang}: +{len(need)}")
        # README
        dst = os.path.join(BASE, f"README.{lang}.md")
        if not done(f"README:{lang}", readme_src):
            body = translate_book(open(readme_src, encoding="utf-8").read(), lang)
            body = re.sub(r"\(book/", f"(book/{lang}/", body)
            open(dst, "w", encoding="utf-8").write(body)
            mark(f"README:{lang}", readme_src)
            log(f"README.{lang}.md ok")
        # book files
        outdir = os.path.join(BASE, "book", lang)
        os.makedirs(outdir, exist_ok=True)
        for f in files:
            src = os.path.join(BASE, "book", f)
            if done(f"{f}:{lang}", src): continue
            t0 = time.time()
            try:
                out = translate_book(open(src, encoding="utf-8").read(), lang)
            except Exception as e:
                log(f"{lang} {f}: GIVE UP {e}")
                return False
            open(os.path.join(outdir, f), "w", encoding="utf-8").write(out)
            mark(f"{f}:{lang}", src)
            save_state_shim()
            log(f"{lang} {f}: {time.time()-t0:.0f}s ({sum(1 for s in state) if False else len(state)} done)")
    log(f"ALL LANGS FINISHED in {(time.time()-t00)/60:.1f} min")
    return True

FORCE = "--force" in sys.argv
def save_state_shim(): pass
if __name__ == "__main__":
    langs = ["en", "km"]
    for a in sys.argv:
        if a.startswith("--langs="): langs = a.split("=", 1)[1].split(",")
    ok = False
    try:
        ok = run(langs)
    except Exception as e:
        log(f"FATAL {e}")
    log(f"exit ok={ok}")
    sys.exit(0 if ok else 1)
