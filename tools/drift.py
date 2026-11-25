#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
drift.py — 译名漂移适配层
=========================
问题：同一部小说不同译本/版次，俄文译名的用字会漂移。
      映射表的「原译名」按 A 版写，正文可能是 B 版 → 直接匹配全部漏掉。

方案：三层解耦，换版次不用改表
  L1 音译等价类 —— 同音汉字折叠（柯/科、费/菲、托/陀…）
  L2 变体探测   —— 由表内原形自动生成「换字/丢字」候选，回正文计数
  L3 漂移文件   —— names/drift/<书>.json 存人工确认的变体，引擎自动并入

产物：
  names/drift/<书>.candidates.json   自动生成（候选，不生效）
  names/drift/<书>.json              人工确认（生效）

用法：
  py -X utf8 tools/drift.py scan            # 探测漂移，出报告 + 候选文件
  py -X utf8 tools/drift.py stat            # 看等价类与漂移规模
  py -X utf8 tools/drift.py accept <书>     # 把候选全部转为生效（快速起步）
"""
import os, sys, re, json, glob, io
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

MAPS_DIR = os.path.join('names', 'maps')
DRIFT_DIR = os.path.join('names', 'drift')

# ---------------- L1 音译等价类 ----------------
EQUIV = {}


def _g(*chars):
    """注册音译等价类。若某字已注册则跳过，防止重复注册覆盖（历史 bug）。"""
    base = chars[0]
    for c in chars:
        if c in EQUIV:
            continue
        EQUIV[c] = base


# ---- 俄文译名常见同音异写（首字为基准形）----
_g('科', '柯', '珂', '蝌', '轲')
_g('费', '菲', '斐', '啡')
_g('奥', '敖', '傲', '澳')
_g('尔', '耳', '迩')
_g('夫', '甫', '福', '富', '傅', '孚')
_g('托', '陀', '妥', '拓')
_g('娃', '瓦', '洼', '袜')
_g('娜', '纳', '那', '呐')
_g('尼', '倪', '妮', '泥')
_g('米', '密', '迷', '谜', '弥')
_g('维', '威', '韦', '唯')
_g('德', '得', '特')
_g('斯', '司', '丝', '思')
_g('耶', '叶', '也')
_g('列', '烈', '裂')
_g('拉', '喇', '腊', '辣', '啦')
_g('罗', '洛', '萝')
_g('谢', '些', '歇')
_g('奇', '契', '齐')
_g('佐', '左')
_g('岑', '琴', '秦', '沁')
_g('布', '卜')
_g('普', '浦')
_g('格', '戈', '葛', '阁')
_g('卢', '鲁', '路')
_g('亚', '雅', '娅', '琊')
_g('基', '吉', '姬')
_g('佳', '嘉', '加')
_g('卡', '喀', '咖')
_g('萨', '莎')
_g('桑', '索')
_g('力', '里', '利', '莉', '丽', '历', '李')
_g('次', '茨', '慈', '词')
_g('蒂', '季', '迪', '狄')
_g('京', '金', '津')
_g('采', '蔡', '彩', '菜')
_g('申', '什', '绅')
_g('乔', '焦', '桥', '侨')
_g('农', '浓', '脓')
_g('日', '热')
_g('尤', '犹', '优')
_g('伊', '依', '衣')
_g('美', '梅', '玫')
_g('丁', '汀')
_g('宁', '凝')
_g('姆', '母')

# 反查：某字的等价集合
CLASSES = defaultdict(set)
for k, v in EQUIV.items():
    CLASSES[v].add(v)
    CLASSES[v].add(k)
CLASSES = {k: sorted(v) for k, v in CLASSES.items()}


def canon(s):
    return ''.join(EQUIV.get(c, c) for c in s)


def canon_hits(text, form):
    """音译规范化匹配：把整篇文本按等价类折叠后正则查找，
    能一次抓出任意多处异写的变体（如 格里高力 ↔ 葛利高里）。
    返回 {实际写法: 次数}（不含与 form 完全相同的）
    """
    cf = canon(form)
    if not cf:
        return {}
    # 文本按 1:1 折叠，长度不变 → 命中位置可直接映射回原字
    ctext = ''.join(EQUIV.get(c, c) for c in text)
    out = Counter()
    for m in re.finditer(re.escape(cf), ctext):
        s, e = m.start(), m.end()
        actual = text[s:e]
        if actual != form:
            out[actual] += 1
    return dict(out)


# ---------------- L2 变体探测 ----------------
def gen_variants(f, max_del=1, max_sub=2):
    """由原形生成「换字/丢字」候选"""
    out = {}
    n = len(f)
    # 丢字
    if max_del >= 1:
        for i in range(n):
            v = f[:i] + f[i + 1:]
            if len(v) >= 2:
                out.setdefault(v, 'del')
    # 换字（等价类内）
    for i, ch in enumerate(f):
        alts = CLASSES.get(EQUIV.get(ch, ch), [])
        for a in alts:
            if a != ch:
                v = f[:i] + a + f[i + 1:]
                out.setdefault(v, 'sub')
    # 丢字 + 换字
    if max_sub >= 2:
        dels = [f[:i] + f[i + 1:] for i in range(n)]
        for d in dels:
            for i, ch in enumerate(d):
                alts = CLASSES.get(EQUIV.get(ch, ch), [])
                for a in alts:
                    if a != ch:
                        v = d[:i] + a + d[i + 1:]
                        out.setdefault(v, 'del+sub')
    return out


def table_forms(bk):
    """取出表内所有「原形」及其归属人物"""
    res = []
    for g in bk['groups']:
        for c in g['characters']:
            F = c['forms'] or {}
            fs = []
            fs += [p for p in F.get('origin_parts', []) if p and len(p) >= 3]
            fs += [p for p in F.get('origin_inner', []) if p and len(p) >= 3]
            fs += [a for a in F.get('aka', []) if a and len(a) >= 3]
            for f in dict.fromkeys(fs):
                res.append((c['hanhua'], f))
    return res


def build_known_spans(text, known_forms):
    """表中已知形态在正文里的位置跨度（用于扣除碎片）"""
    forms = sorted({f for f in known_forms if f}, key=len, reverse=True)
    if not forms:
        return []
    rx = re.compile('|'.join(re.escape(f) for f in forms))
    return [(m.start(), m.end()) for m in rx.finditer(text)]


def net_count(text, v, known_spans):
    """净出现：v 的所有出现中，不作为已知形态子串的次数"""
    total = text.count(v)
    if total == 0:
        return 0, 0, 0.0
    net = 0
    for m in re.finditer(re.escape(v), text):
        s, e = m.start(), m.end()
        if any(ks <= s and e <= ke for ks, ke in known_spans):
            continue
        net += 1
    return net, total, net / total


KIND_RANK = {'sub': 0, 'del+sub': 1, 'del': 2}
MIN_LEN_LOSSY = 3          # 丢字型候选的最短长度（低于此几乎全是碎片）


def suppress_siblings(cands):
    """剔除“同源候选的子串”：如 夫洛维奇 ⊂ 巴夫洛维奇"""
    out = {}
    for v, meta in cands.items():
        if any(v != w and v in w and cands[w]['count'] >= meta['count'] for w in cands):
            continue
        out[v] = meta
    return out


def scan_book(title, bk, text, minfreq=2, include_hit=False, min_ratio=0.25):
    rows = []
    all_forms = {f for _, f in table_forms(bk)}
    known_spans = build_known_spans(text, all_forms)
    for hanhua, f in table_forms(bk):
        direct = text.count(f)
        if direct > 0 and not include_hit:
            continue
        cands = {}
        # ---- A. 音译规范化匹配（主力：任意多处异写）----
        for actual, c in canon_hits(text, f).items():
            if c >= minfreq:
                cands[actual] = {'count': c, 'total': c, 'kind': 'canon', 'ratio': 1.0}
        # ---- B. 变形生成（补充：丢字 / 短碎片）----
        for v, kind in gen_variants(f).items():
            if v in cands:
                continue
            if kind in ('del', 'del+sub') and len(v) < MIN_LEN_LOSSY:
                continue
            net, total, ratio = net_count(text, v, known_spans)
            if net < minfreq:
                continue
            if kind in ('del', 'del+sub') and ratio < min_ratio:
                continue
            cands[v] = {'count': net, 'total': total, 'kind': kind, 'ratio': round(ratio, 2)}
        cands = suppress_siblings(cands)
        # 剔除“纯粹是自己的一部分”的碎片（去掉首/尾字后与原文无实质差异者）
        if cands:
            ranked = sorted(cands.items(), key=lambda kv: (-kv[1]['count'],))
            rows.append({'hanhua': hanhua, 'form': f, 'direct': direct,
                         'cands': dict(ranked)})
    return rows


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


def cmd_scan(titles=None):
    books = load_books()
    titles = titles or sorted(books)
    os.makedirs(DRIFT_DIR, exist_ok=True)
    buf = io.StringIO()
    total = 0
    for t in titles:
        if t not in books:
            continue
        nf, text = load_novel(t)
        if not text:
            print('正文缺失', t)
            continue
        rows = scan_book(t, books[t], text)
        total += len(rows)
        buf.write('\n' + '=' * 74 + f'\n### {t}  ｜ 漂移项 {len(rows)}  ｜ 正文 {len(text)} 字\n' + '=' * 74 + '\n')
        m = {}
        for r in rows:
            buf.write(f'\n[{r["hanhua"]}] 表内原形「{r["form"]}」直接命中 {r["direct"]}\n')
            ranked = sorted(r['cands'].items(), key=lambda kv: (KIND_RANK.get(kv[1]['kind'], 9), -kv[1]['count']))
            for v, meta in ranked[:6]:
                buf.write(f'      {v:<16} 净{meta["count"]:<5}/总{meta["total"]:<5} {meta["kind"]:<8} 纯{meta["ratio"]:.2f}\n')
            if ranked:
                m[r['form']] = [ranked[0][0]]          # 建议只取最优一个
        if m:
            json.dump({'schema': 'drift/1.0-candidates', 'book': t,
                       'note': '自动生成；确认后另存为 <书>.json 才生效',
                       'map': m},
                      open(os.path.join(DRIFT_DIR, t + '.candidates.json'), 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=2)
    open('_drift_report.txt', 'w', encoding='utf-8').write(buf.getvalue())
    print('漂移项合计', total)
    print('报告 -> _drift_report.txt')
    print('候选 -> names/drift/*.candidates.json')


def cmd_stat():
    print('等价类组数', len(CLASSES), '｜ 覆盖汉字', len(EQUIV))
    for f in sorted(glob.glob('*.txt')):
        t = open(f, 'rb').read().decode('utf-8-sig')
        keys = Counter(canon(w) for w in re.findall(r'[\u4e00-\u9fff]{3,8}', t) if len(w) >= 3)
        print(f'  {f[:24]:<26} 长度3-8片段 {sum(keys.values()):>7}')


def cmd_accept(title):
    p = os.path.join(DRIFT_DIR, title + '.candidates.json')
    if not os.path.exists(p):
        print('无候选文件', p); return
    d = json.load(open(p, encoding='utf-8'))
    d['schema'] = 'drift/1.0'
    d['note'] = '已确认生效'
    json.dump(d, open(os.path.join(DRIFT_DIR, title + '.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print('已生效 ->', os.path.join(DRIFT_DIR, title + '.json'), '共', len(d['map']), '项')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    if cmd == 'scan':
        cmd_scan(sys.argv[2:] or None)
    elif cmd == 'stat':
        cmd_stat()
    elif cmd == 'accept':
        cmd_accept(sys.argv[2])
    else:
        print(__doc__)