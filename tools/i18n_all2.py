# -*- coding: utf-8 -*-
"""Translate the book (zh -> en, km) via tools/tengine (token-safe).

- README.ui.json first: UI strings -> tools/ui_i18n.json
- README.en.md / README.km.md via translate_readme2 rules
- book/*.md: line-structured translation through tengine (links/URLs/paths
  protected by XXnXX tokens). Machine tags and Source values pass verbatim.
- Resumable per file (sha in tools/i18n_progress.json) and per line cache
  (tools/book_cache.<lang>.json). Exits nonzero on snooze budget exhaustion;
  the Windows scheduled task (SastraI18nTranslate) reruns it.
Usage: python tools/i18n_all2.py [--langs=en,km] [--force]
"""
import os, re, sys, json, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tengine as T

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = open(os.path.join(BASE, "tools", "i18n_all2.log"), "a", encoding="utf-8")
def log(m):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True); LOG.write(line + "\n"); LOG.flush()

SKIP_RE = re.compile(r'^\s*(<div|</div>|<img|\[!\[|\[<img|<a\s+href=|\|[\s\-:|]+\|$)')
FIELD = re.compile(r"^(\s*- )(成本|说人话|收益|证据等级|来源|备注)(：)(.*)$")
HL = {"成本": "Cost", "说人话": "Plain words", "收益": "Benefit",
      "证据等级": "Evidence", "来源": "Source", "备注": "Note"}

def tr_line(line, to, cache):
    key = hashlib.md5(line.encode("utf-8")).hexdigest()[:16]
    if key in cache:
        return cache[key]
    res = line
    s = line.strip()
    if SKIP_RE.match(line):
        cache[key] = res
        return res
    try:
        if s and not s.startswith("<!--") and not s.startswith("[← 回总目录]"):
            if s.startswith("|"):
                cells = line.split("|")
                out_cells = []
                for c in cells:
                    cs = c.strip()
                    if cs and T.CJK.search(cs):
                        out_cells.append(" " + T.translate_strict(cs, to) + " ")
                    else:
                        out_cells.append(c)
                res = "|".join(out_cells)
            else:
                m = FIELD.match(line)
                if m:
                    lead, label, _, val = m.groups()
                    tv = val if label in ("来源", "证据等级") else T.translate_strict(val, to)
                    res = f"{lead}{HL[label]}: {tv}"
                elif s.startswith("#"):
                    mh = re.match(r"^(\s*#{1,4} )(\d+\. )?(.*)$", line)
                    head, num, txt = mh.groups()
                    tv = T.translate_strict(txt, to)
                    res = f"{head}{num or ''}{tv}"
                elif T.CJK.search(s):
                    lead = line[:len(line) - len(line.lstrip())]
                    res = lead + T.translate_strict(s, to)
    except Exception:
        pass   # keep original zh line, do NOT cache -> rerun retries it when an engine is back
    if res != line:
        cache[key] = res   # only cache successful translations
    return res

def _slug(s):
    s = re.sub(r"[#*`\[\]]", "", s).strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.U)
    return s.replace(" ", "-")

def translate_md(path, to, cache, beat=None):
    """Line-structured batch translation with per-line md5 cache."""
    src_lines = open(path, encoding="utf-8").read().split("\n")

    # --- 1. plan: which lines need work, extract their translatable segments ---
    todo = []          # (line_no, [ (kind, payload) ], [seg_idx_in_batch])
    segs = []          # flat list of masked segment texts
    for i, line in enumerate(src_lines):
        if hashlib.md5(line.encode("utf-8")).hexdigest()[:16] in cache: continue
        s = line.strip()
        if (not s) or SKIP_RE.match(line) or s.startswith("<!--") or s.startswith("[← 回总目录]"):
            cache[hashlib.md5(line.encode("utf-8")).hexdigest()[:16]] = line
            continue
        plan, seg_idx = [], []
        m = FIELD.match(line)
        if m:
            lead, label, _, val = m.groups()
            if label in ("来源", "证据等级"):
                res = f"{lead}{HL[label]}: {val}"
                cache[hashlib.md5(line.encode("utf-8")).hexdigest()[:16]] = res
                continue
            if T.CJK.search(val):
                mask, spans = T._protect(val)
                segs.append(mask); seg_idx.append((len(segs)-1, spans))
            plan.append(("field", label, lead, val))
        elif s.startswith("#"):
            mh = re.match(r"^(\s*#{1,4} )(\d+\. )?(.*)$", line)
            head, num, txt = mh.groups()
            if T.CJK.search(txt):
                mask, spans = T._protect(txt)
                segs.append(mask); seg_idx.append((len(segs)-1, spans))
            plan.append(("head", head, num, txt))
        elif s.startswith("|"):
            cells = line.split("|")
            for ci, c in enumerate(cells):
                cs = c.strip()
                if cs and T.CJK.search(cs):
                    mask, spans = T._protect(cs)
                    segs.append(mask); seg_idx.append((len(segs)-1, spans))
            plan.append(("table", cells))
        elif T.CJK.search(s):
            lead = line[:len(line) - len(line.lstrip())]
            mask, spans = T._protect(s)
            segs.append(mask); seg_idx.append((len(segs)-1, spans))
            plan.append(("body", lead, s))
        if seg_idx or plan:
            todo.append((i, line, plan, seg_idx))

    # --- 2. batch-translate all segments ---
    translated = T.translate_lines(segs, to) if segs else []
    n_fail = sum(1 for x in translated if x is None or T.residual_cjk(T._restore(x, [])[0]))
    if segs and n_fail == len([s for s in segs if T.CJK.search(s)]):
        # nothing translated (all engines blocked) -> caller should skip writing
        return None

    # --- 3. reassemble lines (verify tokens + no residual CJK) ---
    def seg_value(idx, spans, fallback):
        tr = translated[idx]
        out, tok_ok = T._restore(tr, spans)
        if T.residual_cjk(out) or not tok_ok:
            return T.translate(fallback, to)   # slow single path w/ own verification
        return out

    seg_cursor = 0
    for i, line, plan, seg_idx in todo:
        key = hashlib.md5(line.encode("utf-8")).hexdigest()[:16]
        # map this line's segment slots in order
        slots = list(seg_idx)
        def next_seg(fallback):
            if not slots: return T.translate(fallback, to)
            gidx, spans = slots.pop(0)
            return seg_value(gidx, spans, fallback)
        kind = plan[0][0]
        if kind == "field":
            _, label, lead, val = plan[0]
            res = f"{lead}{HL[label]}: {val}" if not T.CJK.search(val) else f"{lead}{HL[label]}: {next_seg(val)}"
        elif kind == "head":
            _, head, num, txt = plan[0]
            res = f"{head}{num or ''}{txt}" if not T.CJK.search(txt) else f"{head}{num or ''}{next_seg(txt)}"
        elif kind == "table":
            cells = plan[0][1]
            out_cells = []
            for c in cells:
                cs = c.strip()
                if cs and T.CJK.search(cs):
                    out_cells.append(" " + next_seg(cs) + " ")
                else:
                    out_cells.append(c)
            res = "|".join(out_cells)
        else:  # body
            _, lead, s = plan[0]
            res = lead + next_seg(s)
        if res != line and not T.residual_cjk(res):
            cache[key] = res
    stats = {"total": len(todo), "failed": 0}
    for i, line, plan, seg_idx in todo:
        key = hashlib.md5(line.encode("utf-8")).hexdigest()[:16]
        if key not in cache and T.residual_cjk(line):
            stats["failed"] += 1
    src_lines = [cache.get(hashlib.md5(l.encode("utf-8")).hexdigest()[:16], l) for l in src_lines]
    if beat: beat()
    txt = "\n".join(src_lines)
    txt = re.sub(r"\]\(book/", f"](book/{to}/", txt)
    # remap same-file anchors: (#translated-heading-slug) must point to the
    # NEW slug of the translated heading it referenced
    anchor_map = {}
    for sl, ol in zip(src_lines, txt.split("\n")):
        mh = re.match(r"^\s*#{1,4} (?:\d+\. )?(.+?)\s*$", sl)
        mo = re.match(r"^\s*#{1,4} (?:\d+\. )?(.+?)\s*$", ol)
        if mh and mo:
            old, new = _slug(mh.group(1)), _slug(mo.group(1))
            if old != new:
                anchor_map[old] = new
    if anchor_map:
        def fix_anchor(m):
            a = m.group(1)
            return "(#" + anchor_map.get(a, a) + ")"
        txt = re.sub(r"\(#[\w\-]+[a-z0-9%\-]*\)", fix_anchor, txt)
    return txt

def main():
    # single-instance lock (scheduled task + manual runs must not collide)
    lockf = os.path.join(BASE, "tools", "i18n.lock")
    if os.path.exists(lockf) and time.time() - os.path.getmtime(lockf) < 3600:
        print("other i18n run active — skip", flush=True)
        return
    open(lockf, "a").close()
    def beat():
        try: os.utime(lockf, None)
        except Exception: pass
    langs = ["en", "km"]
    FORCE = "--force" in sys.argv
    for a in sys.argv:
        if a.startswith("--langs="): langs = a.split("=", 1)[1].split(",")
    prog_path = os.path.join(BASE, "tools", "i18n_progress.json")
    prog = json.load(open(prog_path, encoding="utf-8")) if os.path.exists(prog_path) else {}
    def sha(p): return hashlib.md5(open(p, "rb").read()).hexdigest()[:12]

    readme = os.path.join(BASE, "README.md")
    files = sorted(f for f in os.listdir(os.path.join(BASE, "book")) if f.endswith(".md"))
    todo = 0
    for lang in langs:
        for name, src in [("README.md", readme)] + [(f, os.path.join(BASE, "book", f)) for f in files]:
            if prog.get(f"{name}:{lang}") == sha(src) and not FORCE: continue
            todo += 1
    log(f"resume: {todo} items todo langs={langs}")
    if todo == 0:
        log("ALL DONE (nothing left)"); return

    for lang in langs:
        cachef = os.path.join(BASE, "tools", f"book_cache.{lang}.json")
        cache = json.load(open(cachef, encoding="utf-8")) if os.path.exists(cachef) else {}
        # UI strings first (small)
        uitgt = os.path.join(BASE, "tools", "ui_i18n.json")
        ui = json.load(open(uitgt, encoding="utf-8")) if os.path.exists(uitgt) else {}
        try:
            from i18n_ui_strings import STR
            ui.setdefault(lang, {})
            need = {k: v for k, v in STR.items() if k not in ui[lang]}
            if need:
                for k, v in need.items():
                    ui[lang][k] = T.translate(v, lang)
                json.dump(ui, open(uitgt, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                log(f"ui.{lang}: +{len(need)}")
        except Exception as e:
            log(f"ui.{lang}: fail {e}")
        # README
        if prog.get(f"README.md:{lang}") != sha(readme) or FORCE:
            txt = translate_md(readme, lang, cache, beat)
            json.dump(cache, open(cachef, "w", encoding="utf-8"), ensure_ascii=False)
            if txt is None:
                log(f"README.{lang}: no engine this pass — other files continue")
            else:
                bar = ("**Language:** [简体中文](README.md) · [English](README.en.md) · [ខ្មែរ](README.km.md)" if lang != "km"
                       else "**ភាសា:** [简体中文](README.md) · [English](README.en.md) · [ខ្មែរ](README.km.md)")
                txt = re.sub(r"^\*\*语言 / Language:\*\*.*\n+", "", txt, flags=re.M)
                txt = bar + "\n\n" + txt
                open(os.path.join(BASE, f"README.{lang}.md"), "w", encoding="utf-8").write(txt)
                left = sum(1 for l in txt.split("\n") if T.residual_cjk(l) and not SKIP_RE.match(l))
                if left == 0:
                    prog[f"README.md:{lang}"] = sha(readme)
                json.dump(prog, open(prog_path, "w", encoding="utf-8"), indent=1)
                log(f"README.{lang}.md written cjk_left={left}")
        # book
        outdir = os.path.join(BASE, "book", lang)
        os.makedirs(outdir, exist_ok=True)
        for f in files:
            src = os.path.join(BASE, "book", f)
            if prog.get(f"{f}:{lang}") == sha(src) and not FORCE: continue
            t0 = time.time()
            try:
                txt = translate_md(src, lang, cache, beat)
            except Exception as e:
                json.dump(cache, open(cachef, "w", encoding="utf-8"), ensure_ascii=False)
                log(f"{lang} {f}: BLOCKED {e} — resume later")
                sys.exit(1)
            json.dump(cache, open(cachef, "w", encoding="utf-8"), ensure_ascii=False)
            if txt is None:
                log(f"{lang} {f}: no engine this pass")
                continue
            open(os.path.join(outdir, f), "w", encoding="utf-8").write(txt)
            left = sum(1 for l in txt.split("\n") if T.residual_cjk(l) and not SKIP_RE.match(l) and not l.strip().startswith(("- Source:", "- 来源：", "来源")))
            if left == 0:
                prog[f"{f}:{lang}"] = sha(src)   # fully translated -> mark done
            json.dump(prog, open(prog_path, "w", encoding="utf-8"), indent=1)
            beat()
            log(f"{lang} {f}: {time.time()-t0:.0f}s cjk_left={left}")
    log("ALL LANGS FINISHED")

if __name__ == "__main__":
    try:
        main()
    finally:
        try: os.remove(os.path.join(BASE, "tools", "i18n.lock"))
        except OSError: pass
