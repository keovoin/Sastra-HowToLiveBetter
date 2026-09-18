# -*- coding: utf-8 -*-
"""Batch-translate the book (zh -> en, zh -> km) with Google's free gtx endpoint.

Line-structured on purpose: heading `### N.` markers, `<!-- 成本标签 -->` comments,
field labels, and 来源/Source lines are never sent to the translator, so the data
pipeline (index.html parser + filters) keeps working untouched.

Output layout: book/en/*.md, book/km/*.md (same filenames), README.en.md / README.km.md.
Resumable: skips existing outputs unless --force. Progress -> tools/i18n_progress.json
Usage: python tools/i18n_translate.py            (all langs, all files)
       python tools/i18n_translate.py --langs=en --only=01
"""
import os, re, sys, json, time, urllib.request, urllib.parse, threading

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BASE, "tools", "i18n_progress.json")
FIELD_RE = re.compile(r"^- (成本|说人话|收益|证据等级|来源|备注)：(.*)$")
HLABEL = {"成本": "Cost", "说人话": "Plain words", "收益": "Benefit", "证据等级": "Evidence", "来源": "Source", "备注": "Note"}

lock = threading.Lock()
state = {}

def load_state():
    global state
    if os.path.exists(STATE):
        try: state = json.load(open(STATE, encoding="utf-8"))
        except Exception: state = {}

def save_state():
    with lock:
        json.dump(state, open(STATE, "w", encoding="utf-8"), indent=1)

# ---------- engine: Google gtx (POST) primary, MyMemory fallback. Adaptive pacing. ----------
_pace = [1.2]   # seconds between requests; shrinks when healthy, grows on 429
_fail = [0]
_lock = threading.Lock()

def gtx(part, to="en"):
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=" + to + "&dt=t"
    data = urllib.parse.urlencode({"q": part}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    return "".join(s[0] for s in json.loads(urllib.request.urlopen(req, timeout=45).read().decode())[0] if s[0])

def mm(part, to="en"):
    pair = "zh-CN|" + ("en" if to == "en" else "km")
    # MyMemory caps ~500 chars; call per-sentence-ish
    url = "https://api.mymemory.translated.net/get?q=" + urllib.parse.quote(part) + "&langpair=" + pair
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.loads(urllib.request.urlopen(req, timeout=45).read().decode())
    return r.get("responseData", {}).get("translatedText", "") or ""

def rate():
    time.sleep(_pace[0])

def engine(text, to):
    """Translate one batch (<=1600 chars, multiline). Handles 429 by backing off."""
    for attempt in range(8):
        try:
            rate()
            out = gtx(text, to)
            with _lock:
                if _fail[0] == 0: _pace[0] = max(0.35, _pace[0] * 0.97)
            _fail[0] = 0
            return out
        except urllib.error.HTTPError as e:
            with _lock:
                _fail[0] += 1
                _pace[0] = min(12, _pace[0] * 2.0) if e.code == 429 else _pace[0]
            if e.code == 429:
                time.sleep(min(90, 6 * (attempt + 1)))
                continue
            if e.code in (400, 403):
                try:
                    return mm(text, to)
                except Exception:
                    pass
            if attempt == 7: raise
        except Exception:
            if attempt == 7: raise
            time.sleep(3)
    return text

def translate_chunk(text):
    """Translate a multi-line block, one call per line group, preserving line count."""
    lines = text.split("\n")
    out, buf, bufi = [], [], []
    def flush():
        if not buf: return
        got = engine("\n".join(buf), TARGET)
        glines = got.split("\n")
        if len(glines) != len(buf):   # count drift -> per-line slow path
            glines = [engine(l, TARGET).replace("\n", " ") for l in buf]
        out.extend(glines)
    for ln in lines:
        if len("\n".join(buf + [ln])) > 1500: flush(); buf, bufi = [], []
        buf.append(ln)
    flush()
    return out

def gtx1(text, to): return engine(text, to)
def gtx2(text, to): return engine(text, to)

# ---------- per-file structured translation ----------
def translate_book(text):
    """Return translated markdown preserving structure (line i -> line i)."""
    lines = text.split("\n")
    translatable = []  # (idx, text-to-send)
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s: continue
        if s.startswith("<!--"): continue                      # machine tags verbatim
        if s.startswith("#"):                                  # headings: translate after number
            m = re.match(r"^(#{1,4} )(\d+\. )?(.*)$", ln)
            if m and m[3].strip(): translatable.append((i, m[3]))
            continue
        mf = FIELD_RE.match(s)
        if mf:
            label, val = mf.groups()
            if label == "来源": continue                        # citations verbatim
            if label == "证据等级": continue                    # A/B/C unchanged
            translatable.append((i, val))
        else:
            if s.startswith("[← 回总目录]"): continue           # nav link verbatim
            translatable.append((i, s))
    if not translatable:
        return text
    payload = [t for _, t in translatable]
    got = translate_chunk("\n".join(payload))
    if len(got) != len(payload):
        got = [engine(t, TARGET).replace("\n", " ").strip() for t in payload]
    out = lines[:]
    for (i, _sent), tr in zip(translatable, got):
        s = lines[i].strip()
        mf = FIELD_RE.match(s)
        if mf and mf.group(1) in HLABEL:
            label = mf.group(1)
            lead = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            out[i] = f"{lead}- {HLABEL[label]}: {tr.strip()}"
        elif s.startswith("#"):
            m = re.match(r"^(#{1,4} )(\d+\. )?(.*)$", lines[i])
            out[i] = f"{m.group(1)}{(m.group(2) or '')}{tr.strip()}"
        else:
            lead = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            out[i] = lead + tr.strip()
    # relabel the two copied-verbatim field types for consistency
    result = "\n".join(out)
    result = result.replace("- 证据等级：", "- Evidence: ").replace("- 来源：", "- Source: ")
    return result

# README: translate body, rewrite book/ links to localized dir
def translate_readme(text, lang):
    body = translate_book(text)
    body = re.sub(r"\(book/", f"(book/{lang}/", body)
    body = re.sub(r"\[← 回总目录\]\(\.\./README\.md\)", "[← Contents](../README.md)", body)
    return body

def run(files, langs):
    global TARGET
    for lang in langs:
        TARGET = lang
        # README
        dst = os.path.join(BASE, f"README.{lang}.md")
        if not os.path.exists(dst) or FORCE:
            open(dst, "w", encoding="utf-8").write(translate_readme(open(os.path.join(BASE, "README.md"), encoding="utf-8").read(), lang))
            print(f"[i18n] README.{lang}.md done", flush=True)
        outdir = os.path.join(BASE, "book", lang)
        os.makedirs(outdir, exist_ok=True)
        for f in files:
            src = os.path.join(BASE, "book", f)
            dst = os.path.join(outdir, f)
            if os.path.exists(dst) and os.path.getsize(dst) > 200 and not FORCE:
                continue
            t0 = time.time()
            text = open(src, encoding="utf-8").read()
            try:
                open(dst, "w", encoding="utf-8").write(translate_book(text))
            except Exception as e:
                print(f"[i18n] {lang} {f}: FAIL {e}", flush=True)
                sys.exit(2)   # supervisor restarts and resumes
            with lock:
                state[f"{lang}:{f}"] = time.strftime("%H:%M:%S")
            save_state()
            print(f"[i18n] {lang} {f} ({time.time()-t0:.0f}s)", flush=True)

FORCE = "--force" in sys.argv
def main():
    langs = ["en", "km"]
    only = None
    for a in sys.argv:
        if a.startswith("--langs="): langs = a.split("=", 1)[1].split(",")
        if a.startswith("--only="): only = a.split("=", 1)[1]
    load_state()
    files = sorted(f for f in os.listdir(os.path.join(BASE, "book")) if f.endswith(".md"))
    if only: files = [f for f in files if f.startswith(only)]
    print(f"[i18n] langs={langs} files={len(files)}", flush=True)
    run(files, langs)
    print("[i18n] DONE", flush=True)

main()
