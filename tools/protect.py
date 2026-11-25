#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
protect.py — 专名保护层（v2：以「误伤探测」代替泛化扫描）
======================================================
泛化扫描噪声太大（阿辽沙说 / 伊凡笑了 都是名字+动词，不是专名）。
改为**反向探测**：先跑一遍替换，再找「汉化名 + 地名/机构后缀」的怪组合。

方案：
  names/protect/<书>.json  →  {"blacklist": [...], "keep": [...]}
  build_engine 自动并入 → 引擎的 blacklist / keep

用法：
  py -X utf8 tools/protect.py scan     # 误伤探测（跑一遍替换再找怪组合）
  py -X utf8 tools/protect.py stat
"""
import os, sys, re, json, glob, io
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

MAPS_DIR = os.path.join('names', 'maps')
PROT_DIR = os.path.join('names', 'protect')

# 地名 / 机构 / 称谓后缀（出现在汉化名之后即为误伤信号）
GEO_SUF = ['堡', '市', '省', '县', '镇', '村', '岛', '港', '城', '州', '国', '河', '湖', '山',
           '街', '路', '巷', '桥', '公园', '广场', '教堂', '修道院', '大学', '医院', '旅馆',
           '戏院', '剧院', '车站', '码头', '工厂', '银行', '报', '杂志', '公司', '商行',
           '娃', '斯基', '娜娅']


def load_books():
    out = {}
    for f in sorted(glob.glob(os.path.join(MAPS_DIR, '*.json'))):
        if f.endswith('_manifest.json'):
            continue
        b = json.load(open(f, encoding='utf-8'))
        out[b['book']['title']] = b
    return out


def load_novel(title):
    for f in glob.glob('*.txt'):
        if f.startswith(title):
            return f, open(f, 'rb').read().decode('utf-8-sig')
    return None, None


def read_protect(title):
    p = os.path.join(PROT_DIR, title + '.json')
    if not os.path.exists(p):
        return {'blacklist': [], 'keep': []}
    d = json.load(open(p, encoding='utf-8'))
    d.setdefault('blacklist', [])
    d.setdefault('keep', [])
    return d


def hanhua_names(title):
    bk = load_books()[title]
    out = set()
    for g in bk['groups']:
        for c in g['characters']:
            if c['hanhua']:
                out.add(c['hanhua'])
    return out


def detect(title, text):
    """跑一遍替换，找「汉化名+地名后缀」怪组合"""
    from localize_names import localize
    engp = os.path.join('names', 'engine', title + '.json')
    eng = json.load(open(engp, encoding='utf-8'))
    doc = json.loads(json.dumps(eng))
    doc['mode'] = 'A'
    new, _, _ = localize(text, doc)

    names = hanhua_names(title)
    hits = Counter()
    for nm in names:
        if len(nm) < 2:
            continue
        for suf in GEO_SUF:
            pat = re.escape(nm) + re.escape(suf)
            for m in re.finditer(pat, new):
                s = m.start()
                ctx = new[max(0, s - 12):m.end() + 8]
                hits[new[s:m.end()]] += 1
    return hits


def cmd_scan(titles=None):
    books = load_books()
    titles = titles or sorted(books)
    os.makedirs(PROT_DIR, exist_ok=True)
    buf = io.StringIO()
    for t in titles:
        nf, text = load_novel(t)
        if not text:
            continue
        hits = detect(t, text)
        cur = read_protect(t)
        buf.write('\n' + '=' * 70 + f'\n### {t} ｜ 误伤信号 {len(hits)} 项\n' + '=' * 70 + '\n')
        auto = []
        for w, n in hits.most_common(30):
            mark = ' ✔已保护' if any(w.startswith(b) for b in cur['blacklist']) else ''
            buf.write(f'  {w:<16} ×{n}{mark}\n')
            if not mark:
                auto.append(w)
        # 从误伤词反推应保护的原文（去掉汉化名，还原成原词较难 → 给候选词本身）
        if auto:
            buf.write(f'\n  → 待保护候选：{auto}\n')
    open('_protect_report.txt', 'w', encoding='utf-8').write(buf.getvalue())
    print('报告 -> _protect_report.txt')


def cmd_stat():
    for f in sorted(glob.glob(os.path.join(PROT_DIR, '*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        print(f'  {os.path.basename(f)}: blacklist={d.get("blacklist")} keep={d.get("keep")}')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    if cmd == 'scan':
        cmd_scan(sys.argv[2:] or None)
    else:
        cmd_stat()