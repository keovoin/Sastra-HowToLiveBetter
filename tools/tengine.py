# -*- coding: utf-8 -*-
"""Shared zh->X translation engine, token-safe, with per-engine circuit breakers.

Engines (tried in order, each auto-skipped while its breaker is open):
  gtx         Google free  — best quality, IP rate-limited (429 = long cooldown)
  mymemory    MyMemory     — fast, small daily quota
  pollinations free LLM    — smart w/ markdown, slow (big spacing), 502-prone

Structure protection: markdown links [text](target), <URLs>, bare https URLs
and book/..|docs/..*.md paths are masked to XXnXX before translation and
restored after; a translation that eats a token is retried with the next engine.
"""
import os, re, time, json, urllib.request, urllib.parse, urllib.error

PROTECT = re.compile(
    r"(\]\([^)\n]*\)"
    r"|<https?://[^\s>\u4e00-\u9fff]+>"
    r"|https?://[^\s)>\]\u4e00-\u9fff]+"
    r"|(?:book|docs)/[^\s)\]<>\u4e00-\u9fff]+\.md)")
TOKEN = re.compile(r"XX(\d+)XX")
CJK = re.compile(r'[\u4e00-\u9fff]')

GAP = {"gtx":  float(os.environ.get("I18N_GAP_GTX", "1.2")),
       "mm":   float(os.environ.get("I18N_GAP_MM", "4.0")),
       "poll": float(os.environ.get("I18N_GAP_POLL", "22.0"))}
BLOCK = {"gtx": 0.0, "mm": 0.0, "poll": 0.0}
BREAK = float(os.environ.get("I18N_BREAK", "900"))          # default breaker window


def gtx(text, to):
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=" + to + "&dt=t"
    data = urllib.parse.urlencode({"q": text[:1500]}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    return "".join(s[0] for s in json.loads(urllib.request.urlopen(req, timeout=30).read().decode())[0] if s[0])


def mymemory(text, to):
    pair = "zh-CN|" + ("en" if to == "en" else "km")
    url = ("https://api.mymemory.translated.net/get?q=" + urllib.parse.quote(text[:480]) +
           "&langpair=" + pair + "&de=keovoin@users.noreply.github.com")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    s = (r.get("responseData") or {}).get("translatedText") or ""
    if not s or "MYMEMORY WARNING" in s.upper() or "QUERY LENGTH" in s.upper():
        raise RuntimeError("mymemory quota/empty")
    return s


def pollinations(text, to):
    lang = "English" if to == "en" else "Khmer (Cambodian)"
    body = json.dumps({"model": "openai",
        "messages": [{"role": "system", "content":
            "Translate the user's Simplified Chinese text to " + lang + " ONLY. "
            "Output only the translation, no preamble. Keep ALL markdown, URLs, "
            "numbers and XX digit XX placeholder tokens byte-identical."},
            {"role": "user", "content": text[:1400]}],
        "max_tokens": 2500, "temperature": 0.1, "referrer": "sastra-i18n"}).encode()
    req = urllib.request.Request("https://text.pollinations.ai/openai", data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    r = json.loads(urllib.request.urlopen(req, timeout=150).read().decode())
    s = (r["choices"][0]["message"].get("content") or "").strip()
    if not s: raise RuntimeError("pollinations empty")
    return s


DEF = {gtx: ("gtx", 3600), mymemory: ("mm", 2400), pollinations: ("poll", 900)}


def _protect(text):
    spans = []
    def rep(m):
        spans.append(m.group(0))
        return f"XX{len(spans)-1}XX"
    return PROTECT.sub(rep, text), spans


def _restore(text, spans):
    found = [int(m) for m in TOKEN.findall(text)]
    out = TOKEN.sub(lambda m: spans[int(m.group(1))] if int(m.group(1)) < len(spans) else m.group(0), text)
    return out, all(i in found for i in range(len(spans)))


def _split_safe(masked, size):
    """Cut masked text into <=size pieces without splitting XXnXX tokens."""
    parts, i = [], 0
    while i < len(masked):
        j = min(i + size, len(masked))
        if j < len(masked):
            for m in TOKEN.finditer(masked):
                if m.start() < j < m.end():
                    j = m.end(); break
        parts.append(masked[i:j]); i = j
    return parts


def _call(fn, part, to):
    name, cd = DEF[fn]
    soft_streak = 0
    for attempt in range(6):
        try:
            time.sleep(GAP[name])
            got = fn(part, to)
            return got
        except Exception as e:
            code = getattr(e, "code", None)
            hard = isinstance(e, urllib.error.HTTPError) and code in (429, 402, 403, 414)
            soft = isinstance(e, urllib.error.HTTPError) and code in (500, 502, 503, 520, 521, 529)
            if hard:
                BLOCK[name] = time.time() + cd
                return None
            if soft:
                soft_streak += 1
                if soft_streak >= 5:
                    BLOCK[name] = time.time() + min(cd, 180)
                    return None
                time.sleep(10)
                continue
            time.sleep(8)
    BLOCK[name] = time.time() + min(cd, 300)
    return None


def residual_cjk(text):
    masked, _ = _protect(text)
    return bool(CJK.search(masked))


def translate(text, to):
    """Translate one segment; best-effort output (original zh only if every engine fails)."""
    if not text.strip() or not CJK.search(text):
        return text
    masked, spans = _protect(text)
    best = None
    for fn, size in ((gtx, 1500), (mymemory, 470), (pollinations, 1400)):
        name = DEF[fn][0]
        if time.time() < BLOCK.get(name, 0.0):
            continue
        acc = []
        ok = True
        for part in _split_safe(masked, size):
            got = _call(fn, part, to)
            if got is None: ok = False; break
            acc.append(got)
        if not ok:
            continue
        out, tok_ok = _restore("".join(acc), spans)
        if not residual_cjk(out):
            return out
        if tok_ok:
            best = out
    return best if best is not None else text


def translate_strict(text, to):
    out = translate(text, to)
    if residual_cjk(out):
        raise RuntimeError("no engine available for: " + text[:50])
    return out


def translate_any(text, to):
    out = translate(text, to)
    return out, out != text


# ---------------- batched lines (numbered, verified) ----------------
NUM = re.compile(r"^\s*(\d{1,3})[:.\)]\s?")

def translate_lines(texts, to):
    """Translate a list of already-masked strings in as few API calls as possible.
    Returns list of translated (still masked) strings, same length. Lines the
    engines mangled fall back to individual translate()."""
    results = [None] * len(texts)
    # build batches of <=12 lines / <=1300 chars
    batches, cur, curlen = [], [], 0
    for i, s in enumerate(texts):
        add = len(s) + 6
        if cur and (len(cur) >= 12 or curlen + add > 1300):
            batches.append(cur); cur, curlen = [], 0
        cur.append(i); curlen += add
    if cur: batches.append(cur)

    for b in batches:
        payload = "\n".join(f"{n+1}: {texts[i]}" for n, i in enumerate(b))
        got = None
        for fn, size, allow in ((gtx, 1500, True), (mymemory, 470, False), (pollinations, 1400, False)):
            if time.time() < BLOCK.get(DEF[fn][0], 0.0): continue
            # small batches only suit gtx/mm partially; pollinations has no size-470 constraint
            pieces = _split_safe(payload, size)
            if len(pieces) > 1 and fn is pollinations and len(pieces) * 30 > 400: continue
            outs = []
            ok = True
            for p in pieces:
                r = _call(fn, p, to)
                if r is None: ok = False; break
                outs.append(r)
            if not ok: continue
            joined = "\n".join(outs)
            parsed = {}
            for ln in joined.split("\n"):
                m = NUM.match(ln)
                if m:
                    n = int(m.group(1))
                    if 1 <= n <= len(b):
                        parsed.setdefault(n, []).append(ln[m.end():])
            if len(parsed) == len(b) and all(len(v) == 1 for v in parsed.values()):
                got = {n: v[0] for n, v in parsed.items()}
                break
            # partial salvage: fill what parsed uniquely, leave rest None
            for n, v in parsed.items():
                if len(v) == 1 and results[b[n-1]] is None:
                    results[b[n-1]] = v[0]
        if got:
            for n, v in got.items():
                results[b[n-1]] = v
    # fallbacks
    for i in range(len(texts)):
        if results[i] is None:
            results[i] = _restore_one(_call_best(texts[i], to), texts[i])
    return results

def _call_best(masked_line, to):
    for fn in (gtx, mymemory, pollinations):
        if time.time() < BLOCK.get(DEF[fn][0], 0.0): continue
        r = _call(fn, masked_line[:1400], to)
        if r is not None: return r
    return None

def _restore_one(got, original_masked):
    if got is None: return original_masked
    return got
