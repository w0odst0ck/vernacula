# -*- coding: utf-8 -*-
"""
localize_names.py — 人名本土化引擎 v2.1

本土化 ≠ 机械替换，四条规则：
  1. 父称消解：中文无父称。「本名·父称·姓」「本名·父称」整体 → 中文全名
     （跨人物笛卡尔积配对，故「莉扎薇塔·伊万诺芙娜」「尼科季姆·福米奇」也能消解）
  2. 语域保留：正式全名 → 全名；昵称/爱称 → 名/小名（不归一化）
  3. 姓不裸用：单独姓氏 → 中文全名（中文叙述不用单字姓）
  4. 同形双译合并：拉斯科利尼科夫 / 拉斯柯尔尼科夫 → 同一人
安全：
  · 最长优先（长模式先匹配，父称随全名一起消解，不会残留）
  · 单遍扫描，无占位符、无链式替换
  · 保护词（彼得堡/彼得大帝）并入模式表并替换为自身，靠最长优先自动胜出
  · 输出前校验原文 hash 不变
"""
import json, re, os, sys, hashlib
from collections import Counter, defaultdict

def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()[:12]

PAT_END = ('维奇', '诺维奇', '内奇', '伊奇', '雷奇', '芙娜', '耶夫娜', '诺芙娜', '夫娜', '沃娜')
PAT_EXACT = ('福米奇', '帕夫雷奇')

def is_pat(w):
    return w in PAT_EXACT or any(w.endswith(s) for s in PAT_END)

SEPS = ('·', '-', '•', '．')          # 正文里常见的姓名字分隔符


def _seps(s):
    """返回同一模式的全部分隔符变体"""
    out = set()
    if '·' in s:
        for sp in SEPS:
            out.add(s.replace('·', sp))
    else:
        out.add(s)
    return out


def build_patterns(doc):
    pats, owners = {}, defaultdict(set)
    giv_owner, sur_owner, nick_owner, inti_owner, full_owner = {}, {}, {}, {}, {}
    all_pats = set()

    for ch in doc['characters']:
        F = ch['forms']
        for g in F.get('given', []):      giv_owner[g] = ch
        for s in F.get('surname', []):    sur_owner[s] = ch
        for n in F.get('nickname', []):   nick_owner[n] = ch
        for i in F.get('intimate', []):   inti_owner[i] = ch
        for f in F.get('full', []):       full_owner[f] = ch
        all_pats.update(F.get('patronymic', []))

    for k in (doc.get('keep') or []):
        if is_pat(k): all_pats.add(k)

    def put(p, t, kind):
        """写入模式，自动展开分隔符变体"""
        if not (p and t):
            return
        for v in _seps(p):
            pats[v] = t
            owners[v].add(t)

    def fullname(ch):
        return ch['localize'].get('full') or ch['localize'].get('surname') or ch['localize'].get('given')

    # 规则1：本名 · 父称 · 姓（3 词）跨人物配对
    for g, ch in giv_owner.items():
        surs = ch['forms'].get('surname', [])
        fs_forms = ch['forms'].get('surname_f', []) or []
        for pt in all_pats:
            for s in list(surs) + list(fs_forms):
                put(f'{g}·{pt}·{s}', fullname(ch), '3w')
    # 规则1b：本名 · 姓（2 词）
    for g, ch in giv_owner.items():
        for s in ch['forms'].get('surname', []):
            put(f'{g}·{s}', fullname(ch), '2ws')
    # 规则1c：本名 · 父称（2 词）跨人物配对
    for g, ch in giv_owner.items():
        for pt in all_pats:
            put(f'{g}·{pt}', fullname(ch), '2wp')

    # 规则2：语域（单名/昵称/爱称）
    for g, ch in giv_owner.items():
        put(g, fullname(ch), 'giv')
    for n, ch in nick_owner.items():
        put(n, ch['localize'].get('nickname') or fullname(ch), 'nick')
    for i, ch in inti_owner.items():
        put(i, ch['localize'].get('intimate') or fullname(ch), 'inti')
    for f, ch in full_owner.items():
        put(f, fullname(ch), 'full')

    # 规则3：姓不裸用 → 中文全名
    for s, ch in sur_owner.items():
        put(s, fullname(ch), 'sur')

    # 规则4：裸父称消解 —— 中文无父称，唯一归属的直接删除（连同前置分隔符）
    pat_owner = defaultdict(set)
    for ch in doc['characters']:
        for pt in ch['forms'].get('patronymic', []):
            pat_owner[pt].add(fullname(ch))
    for pt, hhs in pat_owner.items():
        if len(hhs) == 1 and pt not in (doc.get('keep') or []):
            for sp in SEPS:
                pats[sp + pt] = ''          # 吃掉分隔符 + 父称
                owners[sp + pt].add('__DEL__')
            pats[pt] = ''
            owners[pt].add('__DEL__')

    # 女性姓 → 家族姓
    for f, t in (doc.get('family_surnames') or {}).items():
        put(f, t, 'surf')

    # 保护词（替换为自身）
    for k in (doc.get('keep') or []) + (doc.get('blacklist') or []):
        put(k, k, 'keep')

    conflicts = {p for p, s in owners.items()
                 if len({x for x in s if x not in ('__DEL__', p)}) > 1}
    return pats, conflicts

# 章节标题识别（多形态）
#  A. 第X部 / 第X章 / 第X卷 / 第X回 / 第X节
#  B. 书名当章节号：罪与罚二（某些电子书用书名分章）
CHAP_RE_A = re.compile(r'(?m)^[ \t\u3000]*第[一-鿿\d]{1,6}[部章卷回节]')
CHAP_RE_B = re.compile(r'(?m)^[ \t\u3000]*罪与罚[一二三四五六七八九十百]{1,3}[ \t\u3000]*$')


SENT_END = '。！？…—”'

# 父称/母称后缀：某名字若后接这些后缀，就是父称的一部分，不可单独替换
PAT_SUF_ALL = ('诺维奇', '耶维奇', '维奇', '伊奇', '内奇', '雷奇',
               '诺芙娜', '耶芙娜', '奥芙娜', '夫娜')


def auto_protect_patronymic(text, pats):
    """自动保护：某形态若在正文里作父称词干（后接父称后缀），
    把「词干+后缀」整体加入保护（替换为自身），
    避免本名从父称里被挖出来替换（如 伊万诺维奇 → 柯建业[伊万]诺维奇）。
    靠「最长优先」自动胜出。返回新增条数。
    """
    add = {}
    for p in list(pats):
        if pats[p] == p:
            continue                     # 已是保护词
        if len(p) > 6:
            continue                     # 长形不可能是父称词干
        for suf in PAT_SUF_ALL:
            combo = p + suf
            if combo in pats or combo in add:
                continue
            if combo in text:
                add[combo] = combo
    pats.update(add)
    return len(add)


def chapter_bounds(text):
    """返回章节起点位置列表（含 0），并合并重复标题行
    合并条件：间隔小 且 中间没有正文（无句末标点）
    """
    pts = [m.start() for m in CHAP_RE_A.finditer(text)]
    pts += [m.start() for m in CHAP_RE_B.finditer(text)]
    pts = sorted(set(pts))
    merged = []
    for p in pts:
        if merged:
            prev = merged[-1]
            gap = p - prev
            if gap < 120:
                between = text[prev:p]
                # 中间无句末标点 → 只是重复标题行，合并
                if not any(ch in between for ch in SENT_END):
                    continue
        merged.append(p)
    if not merged or merged[0] != 0:
        merged = [0] + merged
    return merged


def localize(text, doc):
    pats, conflicts = build_patterns(doc)
    # 冲突模式一律降级为「保留原文」→ 不误伤
    for p in conflicts:
        pats[p] = p
    # 父称词干保护（防本名从父称里被挖走）
    auto_protect_patronymic(text, pats)
    mode = doc.get('mode', 'B')
    br = doc.get('brackets') or '[]'
    ob, cb = (br[0], br[1]) if len(br) >= 2 else ('[', ']')

    keys = sorted(pats, key=len, reverse=True)
    rx = re.compile('|'.join(re.escape(k) for k in keys))
    cnt = Counter()

    def make_sub(seen):
        def sub(m):
            s = m.group(0)
            to = pats[s]
            if to == s:
                return s                  # 保护词
            cnt[s] += 1
            if to == '':
                return ''                 # 裸父称消解（连分隔符一起吃掉）
            if mode == 'A':
                return to
            if mode == 'C':
                return f'{to}{ob}{s}{cb}'
            # B / C2：该原形「本段内」首次出现时标注它自己
            if s not in seen:
                seen.add(s)
                mark = s if len(s) <= 14 else s[:14]
                return f'{to}{ob}{mark}{cb}'
            return to
        return sub

    if mode == 'C2':
        # 按章切分：每章重置「首见」集合
        bounds = chapter_bounds(text)
        parts = []
        for i, b0 in enumerate(bounds):
            b1 = bounds[i + 1] if i + 1 < len(bounds) else len(text)
            if b1 <= b0:
                continue
            parts.append(rx.sub(make_sub(set()), text[b0:b1]))
        return ''.join(parts), cnt, conflicts

    # A / B / C：全篇一次性处理
    return rx.sub(make_sub(set()), text), cnt, conflicts

def main(txt, js, out=None):
    text = open(txt, 'rb').read().decode('utf-8-sig')
    doc = json.load(open(js, encoding='utf-8'))
    h0 = sha(txt)
    pats, conf = build_patterns(doc)
    new, cnt, _ = localize(text, doc)
    out = out or txt.replace('.txt', '_本土化.txt')
    open(out, 'w', encoding='utf-8').write(new)
    h1 = sha(txt)
    print(f'模式 {len(pats)} 条 | 冲突 {len(conf)} | mode {doc.get("mode","B")}')
    print(f'原文 hash {h0} -> {h1}  {"未改动 OK" if h0 == h1 else "!!被改动"}')
    print(f'替换 {sum(cnt.values())} 处，涉及 {len(cnt)} 种形态')
    print(f'输出: {out}')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)