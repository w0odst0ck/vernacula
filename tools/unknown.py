#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
unknown.py — 表外角色探测与注册
==============================
映射表只覆盖主要角色；小配角（斯穆罗夫、克拉索特金、波乔洛夫…）在表外 →
整本书读到那里就卡壳。本工具负责**发现 → 分类 → 注册**。

三层分类（避免把父称当成新角色）：
  ① 父称类（-维奇/-芙娜/-内奇）：不是角色，是称谓 → 交给「裸父称消解」或 keep
  ② 漂移类：与表内形态同音异写 → 交给 drift 层
  ③ 真·新角色：需要注册

注册：names/unknown/<书>.json
  {"characters": [
     {"origin": "斯穆罗夫", "hanhua": "宋秉文", "role": "中学生",
      "policy": "translit|keep", "forms": {...}}
  ]}
  policy=keep  → 保留原文（默认，零风险）
  policy=translit → 按音译规则生成中文名

用法：
  py -X utf8 tools/unknown.py scan        # 探测 + 分类 + 出候选
  py -X utf8 tools/unknown.py stat        # 看注册表
  py -X utf8 tools/unknown.py draft <书>  # 把候选写成待填草稿
"""
import os, sys, re, json, glob, io
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

MAPS_DIR = os.path.join('names', 'maps')
UNK_DIR = os.path.join('names', 'unknown')
DRIFT_DIR = os.path.join('names', 'drift')

SUR_SUF = ('夫', '娃', '斯基', '茨基', '诺夫', '科夫', '霍夫', '莫夫', '佐夫', '耶夫',
           '洛夫', '罗夫', '采夫', '绍夫', '申', '宁', '金', '京', '奇', '卡', '科',
           '岑', '廖夫', '辛', '连', '乔夫', '季', '宾', '科夫', '洛夫')
PAT_END = ('维奇', '诺维奇', '内奇', '伊奇', '雷奇', '芙娜', '耶夫娜', '诺芙娜',
           '夫娜', '沃娜', '耶芙娜', '奥芙娜', '奇娜')

STOP = set('''说道 的时候 时候 什么 怎么 这样 那样 因为 所以 但是 可是 如果 就是
这个 那个 我们 你们 他们 她们 自己 现在 已经 还是 只是 不能 没有 知道 觉得 起来
出来 下来 过来 进来 上去 下去 出去 回来 上来 一个 一声 一样 一起 一直 一定 一般
哥萨克 军官 将军 上尉 中尉 士兵 老爷 太太 小姐 先生 医生 律师 法官 警察 教堂
修道院 大学 医院 旅馆 车站 码头 工厂 银行 城市 农村 乡下 广场 大街 胡同 院子
房子 屋子 房间 大门 门口 桌子 椅子 床上 身上 手里 心里 眼里 脸上 头上 嘴里
的话 的事 的人 的东西 的地方 的女人 的男人 的心情 的眼睛 的声音 的力量
权利 义务 责任 真理 谎言 上帝 基督 圣母 耶稣 天使 魔鬼 灵魂 精神 思想 感情
爱情 友情 亲情 幸福 痛苦 悲伤 欢乐 愤怒 恐惧 希望 绝望 命运 生活 生命 死亡
'''.split())

CJK_RUN = re.compile(r'[\u4e00-\u9fff]{2,10}')


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


def known_forms(bk):
    fs = set()
    for g in bk['groups']:
        for c in g['characters']:
            F = c['forms'] or {}
            for key in ('origin_parts', 'origin_inner', 'aka', 'nickname', 'petname',
                        'intimate', 'alias'):
                fs |= {p for p in F.get(key, []) if len(p) >= 2}
            if c.get('hanhua'):
                fs.add(c['hanhua'])
    return fs


def drift_forms(title):
    p = os.path.join(DRIFT_DIR, title + '.json')
    if not os.path.exists(p):
        return set()
    d = json.load(open(p, encoding='utf-8'))
    out = set()
    for k, vs in (d.get('map') or {}).items():
        out.add(k)
        out |= set(vs)
    return out


def score(w, text):
    sc, ev = 0, []
    for pat, wt, lab in [(f'{re.escape(w)}说', 3, '说'), (f'{re.escape(w)}问', 3, '问'),
                         (f'{re.escape(w)}回答', 3, '回答'), (f'对{re.escape(w)}', 2, '对XX'),
                         (f'{re.escape(w)}·', 4, '名·父称'), (f'·{re.escape(w)}', 4, '父称·姓'),
                         (f'{re.escape(w)}先生', 3, '先生'), (f'{re.escape(w)}太太', 3, '太太'),
                         (f'{re.escape(w)}将军', 3, '将军'), (f'{re.escape(w)}公爵', 3, '公爵')]:
        c = text.count(pat)
        if c:
            sc += c * wt
            ev.append(f'{lab}×{c}')
    return sc, ev


def classify(title, bk, text, minfreq=3):
    """→ (真新角色列表, 父称列表, 漂移列表)"""
    known = known_forms(bk)
    drifted = drift_forms(title)
    runs = Counter(CJK_RUN.findall(text))
    new, patr, drift = [], [], []
    for w, n in runs.items():
        if n < minfreq or w in STOP or w in known or len(w) < 3:
            continue
        if any(w != f and w in f for f in known):
            continue
        is_pat = any(w.endswith(s) for s in PAT_END)
        looks_sur = any(w.endswith(s) for s in SUR_SUF)
        if not (is_pat or looks_sur):
            continue
        # 漂移类：与表内形态同音
        try:
            from tools.drift import canon, canon_hits
            if w in drifted or canon_hits(text, w):
                drift.append(w)
                continue
        except Exception:
            pass
        sc, ev = score(w, text)
        if sc <= 0:
            continue
        (patr if is_pat else new).append((w, n, sc, ev))
    new.sort(key=lambda x: -x[2])
    patr.sort(key=lambda x: -x[1])
    return new, patr, drift


def cmd_scan(titles=None):
    books = load_books()
    titles = titles or sorted(books)
    os.makedirs(UNK_DIR, exist_ok=True)
    buf = io.StringIO()
    for t in titles:
        if t not in books:
            continue
        nf, text = load_novel(t)
        if not text:
            continue
        new, patr, drift = classify(t, books[t], text)
        buf.write('\n' + '=' * 74 + f'\n### {t}\n' + '=' * 74 + '\n')
        buf.write(f'\n【真·表外角色】{len(new)} 位（建议注册）\n')
        for w, n, sc, ev in new[:25]:
            buf.write(f'  {w:<14} ×{n:<5} 分{sc:<5} {", ".join(ev[:3])}\n')
        buf.write(f'\n【父称类】{len(patr)} 项（不是角色 → 裸父称消解/keep，勿注册）\n')
        buf.write('  ' + ', '.join(w for w, *_ in patr[:20]) + '\n')
        buf.write(f'\n【漂移类】{len(drift)} 项（交给 drift 层）\n')
        buf.write('  ' + ', '.join(drift[:20]) + '\n')
    open('_unknown_report.txt', 'w', encoding='utf-8').write(buf.getvalue())
    print('报告 -> _unknown_report.txt')


def cmd_draft(title):
    books = load_books()
    if title not in books:
        print('no book'); return
    nf, text = load_novel(title)
    new, patr, drift = classify(title, books[title], text)
    os.makedirs(UNK_DIR, exist_ok=True)
    chars = [{'origin': w, 'hanhua': '', 'role': '',
              'policy': 'keep', 'count': n, 'evidence': ev}
             for w, n, sc, ev in new]
    doc = {'schema': 'unknown/1.0', 'book': title,
           'note': '手动填写 hanhua（汉化名）与 policy（keep=保留原文 / translit=参与替换）；hanhua 留空视为 keep',
           'characters': chars}
    p = os.path.join(UNK_DIR, title + '.draft.json')
    json.dump(doc, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'草稿 -> {p}  ({len(chars)} 位)')


def cmd_stat():
    for f in sorted(glob.glob(os.path.join(UNK_DIR, '*.json'))):
        if f.endswith('.draft.json'):
            continue
        d = json.load(open(f, encoding='utf-8'))
        print(f'  {os.path.basename(f)}: {len(d.get("characters", []))} 位')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    a = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == 'scan':
        cmd_scan([a] if a else None)
    elif cmd == 'draft':
        cmd_draft(a)
    else:
        cmd_stat()