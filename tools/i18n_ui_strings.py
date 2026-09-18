# Fetch localized UI chrome strings (incremental, resumable, slow-paced).
import urllib.request, urllib.parse, json, os, time
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "tools", "ui_i18n.json")
STR = {
 "title": "高性价比人生指南",
 "tagline": "用最少的钱、时间和精力，换回最多的寿命、金钱和人身自由",
 "subtitle": "每一条都回答两个问题：花掉什么，换回什么。",
 "search": "搜索条目",
 "all_sections": "全部章节",
 "chapters": "章节",
 "value_for_money": "性价比",
 "vf_note": "作者判断，同口径内可比",
 "benefit_lens": "换回的口径",
 "evidence": "证据等级",
 "evidence_note": "荟萃/RCT · 有研究 · 共识",
 "spend": "花钱",
 "spend_time": "花时间",
 "willpower": "要毅力",
 "only_dispute": "只看标了争议的", "only_todo": "只看有待核实的",
 "reset": "清空筛选",
 "hint1": "章节一次只看一个，成本和等级可多选。同一组多选是「或」，不同组之间是「且」。",
 "hint2": "每节内按性价比从高到低排，检索不改变顺序。",
 "hint3": "正文与标签来自仓库 book/ 下的 32 个文件，改正文即改这里。",
 "cost": "成本", "gain": "收益", "note": "备注", "source": "来源",
 "shown": "当前显示", "of_total": "条，共", "unit": "条",
 "value_badge": "性价比", "evidence_badge": "证据", "grade_unit": "级",
 "disputed": "争议", "unverified": "含待核实",
 "lens_life": "换寿命", "lens_money": "换钱", "lens_time": "换时间精力", "lens_freedom": "换人身自由",
 "cost_none": "不花钱", "cost_low": "花少量钱", "cost_high": "花不少钱",
 "t_quiet": "顺手", "t_hours": "花几小时", "t_daily": "每天占时间",
 "w_no": "不用毅力", "w_some": "要一点毅力", "w_much": "要很多毅力",
 "perma": "本条链接", "gloss_title": "看不懂的缩写和名词",
 "gloss_hint": "正文里带虚线的词，点一下或把鼠标放上去就有解释。全表如下。",
 "empty": "没有匹配的条目。去掉一个筛选条件，或换个更短的关键词。",
 "loading": "正在读取正文 …",
 "long_posts": "长文",
 "ad": "广告",
 "doc_foot": "数字口径以条目内标注为准：不同节使用不同口径（死亡率、精力/时间、金钱、人身自由），互不换算。来源核实过程见 docs/核实记录。Unlicense，公有领域。",
 "noscript": "本页的筛选功能需要 JavaScript。正文可直接阅读：README.md 里的目录，正文在 book/。",
}
def gtx(text, to):
    url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=" + to + "&dt=t"
    data = urllib.parse.urlencode({"q": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent":"Mozilla/5.0"})
    return "".join(s[0] for s in json.loads(urllib.request.urlopen(req, timeout=40).read().decode())[0] if s[0])
def main():
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    for to in ("en","km"):
        out.setdefault(to, {})
        for k, v in STR.items():
            if k in out[to]: continue
            ok = False
            for a in range(10):
                try:
                    out[to][k] = gtx(v, to).strip(); ok = True; break
                except urllib.error.HTTPError as e:
                    time.sleep(20 if e.code == 429 else 5)
                except Exception: time.sleep(5)
            json.dump(out, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
            time.sleep(1.5 if ok else 0)
    print("UI STRINGS DONE", len(out["en"]), len(out["km"]))

if __name__ == "__main__":
    main()
