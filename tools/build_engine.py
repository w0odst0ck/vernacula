#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_engine.py — 映射表 JSON → 引擎配置 JSON
============================================
输入：names/maps/<书>.json    （与人名映射表.xlsx 双向同步）
输出：names/engine/<书>.json  （引擎直接可用；可手工微调，不回写表）

把「给人看的表」翻译成「给机器用的形态表」：
  · 原译名按俄式惯例拆角色：[本名, 父称…, 姓]
  · 备注线索配对：即X（正文原形） ↔ 昵称/小名/爱称"Y"（中文叫法）  →  X=Y
  · 显式配对语法（优先级更高）：  米卡=明嘉  ；多个用 、 或 ;
  · 正文形态列（可选第4列）：直接补充该人物在正文里的全部写法
  · 家族姓：同姓 ≥2 人 → 家族统称（卡拉马佐夫→马家）

去重规则（防冲突）：
  · 昵称原形若与「本名/姓」重复 → 跳过（否则同一形态两个目标，必冲突）
  · 姓已进 family_surnames → 从个人 forms 里移除，由家族统称接管
用法：py -X utf8 tools/build_engine.py [mapsdir] [outdir]
"""
import sys, os, re, json, glob
from collections import defaultdict

DEFAULT_IN = os.path.join('names', 'maps')
DEFAULT_OUT = os.path.join('names', 'engine')
DRIFT_DIR = os.path.join('names', 'drift')
PROT_DIR = os.path.join('names', 'protect')
UNK_DIR = os.path.join('names', 'unknown')

SUR_END = ('夫', '娃', '斯基', '茨基', '诺夫', '科夫', '霍夫', '莫夫', '佐夫', '耶夫',
           '洛夫', '罗夫', '采夫', '绍夫', '申', '宁', '金', '京', '奇', '卡')
TITLE_SUF = ('长老', '神父', '上尉', '太太', '老爹', '爷爷', '先生', '公爵', '伯爵', '将军')

PAIR_RE = re.compile(r'([\u4e00-\u9fff·]{2,12})\s*[=＝]\s*([\u4e00-\u9fff]{1,8})')
SPLIT_RE = re.compile(r'[、,，;；\s]+')


def is_surname_like(w):
    return any(w.endswith(s) for s in SUR_END)


def is_title_like(w):
    return any(w.endswith(s) for s in TITLE_SUF)


def split_forms(s):
    return [x for x in SPLIT_RE.split(s or '') if x]


def load_drift(title):
    """读漂移层：{表内原形: [正文变体...]}"""
    p = os.path.join(DRIFT_DIR, title + '.json')
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding='utf-8'))
    return d.get('map') or {}


def load_protect(title):
    """读专名保护层：{"blacklist": [...], "keep": [...]}"""
    p = os.path.join(PROT_DIR, title + '.json')
    if not os.path.exists(p):
        return {'blacklist': [], 'keep': []}
    d = json.load(open(p, encoding='utf-8'))
    return {'blacklist': d.get('blacklist') or [], 'keep': d.get('keep') or []}


def load_unknown(title):
    """读表外角色注册表
    返回 (characters, keep_list)
      policy=translit → 生成角色条目参与替换
      policy=keep     → 加入 keep（保留原文）
    兼容两种写法：characters 列表，或 {origin: hanhua} 字典
    """
    p = os.path.join(UNK_DIR, title + '.json')
    if not os.path.exists(p):
        return [], []
    d = json.load(open(p, encoding='utf-8'))
    raw = d.get('characters')
    chars, keep = [], []
    if isinstance(raw, dict):
        for origin, hanhua in raw.items():
            (chars.append({'origin': origin, 'hanhua': hanhua, 'policy': 'translit'})
             if hanhua else keep.append(origin))
        return chars, keep
    for c in (raw or []):
        origin = c.get('origin')
        if not origin:
            continue
        pol = c.get('policy', 'keep')
        hh = c.get('hanhua') or ''
        if pol == 'translit' and hh:
            chars.append({**c, 'hanhua': hh})
        else:
            keep.append(origin)
            # 注册表里可能有变体形态
            for f in (c.get('variants') or []):
                keep.append(f)
    return chars, keep


def build_unknown_chars(characters):
    """把注册的表外角色转成引擎 characters 条目"""
    out = []
    for i, c in enumerate(characters):
        origin, hh = c['origin'], c['hanhua']
        loc = {'full': hh, 'given': hh}
        if len(hh) > 1:
            loc['surname'] = hh[0]
        forms = {'given': [origin]}
        for v in (c.get('variants') or []):
            forms['given'].append(v)
        out.append({'id': 'u%02d' % (i + 1), 'hanhua': hh,
                    'role': c.get('role', '表外角色'), 'localize': loc,
                    'forms': forms, '_source': 'unknown'})
    return out


def apply_drift(ch, drift):
    """把漂移变体按角色并入 forms：变体继承原形的角色"""
    added = 0
    for role, lst in list(ch['forms'].items()):
        extra = []
        for f in lst:
            for v in drift.get(f, []):
                if v and v not in extra:
                    extra.append(v)
        if extra:
            ch['forms'][role] = list(dict.fromkeys(lst + extra))
            added += len(extra)
    return added


def build_book(bk, drift=None, protect=None, unknown=None):
    drift = drift or {}
    protect = protect or {'blacklist': [], 'keep': []}
    unk_chars, unk_keep = unknown or ([], [])
    keep = list(protect.get('keep') or []) + list(unk_keep)
    blacklist = list(protect.get('blacklist') or [])
    chs, fam = [], defaultdict(list)
    seen_forms = {}          # form -> hanhua（跨人物查重）

    for g in bk['groups']:
        for c in g['characters']:
            F = c['forms']
            parts = list(F.get('origin_parts') or [])
            inner = list(F.get('origin_inner') or [])
            extra = split_forms(c.get('text_forms', ''))
            hh = c['hanhua']
            if not hh:
                continue

            # --- 角色拆分（俄式：本名·父称·姓）---
            given, patr, sur = [], [], []
            if len(parts) >= 3:
                given, patr, sur = [parts[0]], parts[1:-1], [parts[-1]]
            elif len(parts) == 2:
                given, patr = [parts[0]], [parts[1]]
            elif len(parts) == 1:
                p = parts[0]
                if is_title_like(p) or not is_surname_like(p):
                    given = [p]
                else:
                    sur = [p]
            for x in inner + extra:
                if is_surname_like(x) and not sur:
                    sur.append(x)
                else:
                    given.append(x)

            # --- 中文形态 ---
            loc = {'full': hh}
            if sur and len(hh) > 1:
                loc['surname'] = hh[0]
                loc['given'] = hh
                loc['given_short'] = hh[1:]
            else:
                loc['given'] = hh
            if is_title_like(parts[0] if parts else ''):
                loc['given'] = hh

            forms = {}
            if sur:
                forms['surname'] = sur
            if given:
                forms['given'] = given
            if patr:
                forms['patronymic'] = patr

            # --- 别名配对（显式 A=B 优先）---
            pairs = PAIR_RE.findall(c.get('note', '') or '')
            if pairs:
                nick, alias = [a for a, _ in pairs], [b for _, b in pairs]
            else:
                aka = list(F.get('aka') or [])
                nick, alias = [], []
                occupied = set(sur) | set(given) | set(patr) | set(inner) | set(extra)
                for lst in (F.get('nickname') or [], F.get('petname') or [], F.get('intimate') or []):
                    for y in lst:
                        src = None
                        for a in aka:
                            if a not in occupied and a not in nick:
                                src = a
                                break
                        if src:                      # 有独立原形才算昵称
                            nick.append(src)
                            alias.append(y)
            if nick:
                forms['nickname'] = nick
                loc['nickname'] = alias[0]
                if len(alias) > 1:
                    forms['intimate'] = nick[1:]
                    loc['intimate'] = alias[1]

            # --- 跨人物查重：同一形态只能有一个目标 ---
            conflicts = []
            for kind, lst in list(forms.items()):
                kept = []
                for f in lst:
                    if f in seen_forms and seen_forms[f] != hh:
                        conflicts.append((f, kind, seen_forms[f]))
                        continue
                    seen_forms[f] = hh
                    kept.append(f)
                if kept:
                    forms[kind] = kept
                else:
                    forms.pop(kind, None)

            ch = {'id': 'c%02d' % (len(chs) + 1), 'hanhua': hh,
                  'role': c.get('note', ''), 'localize': loc, 'forms': forms}
            nd = apply_drift(ch, drift)
            if nd:
                ch['_drift'] = nd
            if conflicts:
                ch['_conflicts'] = conflicts
            chs.append(ch)
            if sur:
                fam[sur[0]].append(hh)

    # --- 表外角色：并入（policy=translit 的才参与替换）---
    for ch in build_unknown_chars(unk_chars):
        # 查重：注册的形态不得与已有人物冲突
        ok = True
        for lst in ch['forms'].values():
            for f in lst:
                if f in seen_forms and seen_forms[f] != ch['hanhua']:
                    ok = False
        if not ok:
            continue
        for lst in ch['forms'].values():
            for f in lst:
                seen_forms[f] = ch['hanhua']
        chs.append(ch)

    # --- 家族姓：同姓 ≥2 人 → 家族统称；并从个人 forms 移除该姓 ---
    family_surnames = {}
    for s, members in fam.items():
        if len(set(members)) >= 2:
            common = os.path.commonprefix(sorted(set(members)))
            if common:
                family_surnames[s] = common + '家'
    for ch in chs:
        surs = ch['forms'].get('surname')
        if surs and surs[0] in family_surnames:
            # 关键：登记「全部」姓形态（含漂移变体），否则变体会被丢弃
            fam_name = family_surnames[surs[0]]
            for s in surs:
                family_surnames.setdefault(s, fam_name)
            ch['forms'].pop('surname', None)
            ch['localize'].setdefault('surname', ch['localize']['full'][0])

    return {
        'schema_version': '3.0-engine',
        'book': {'id': bk['book'].get('title'), 'title': bk['book'].get('title')},
        'characters': chs,
        'family_surnames': family_surnames,
        'keep': keep,
        'blacklist': blacklist,
        'mode': 'B',
    }


def main(indir=DEFAULT_IN, outdir=DEFAULT_OUT):
    os.makedirs(outdir, exist_ok=True)
    files = sorted(f for f in glob.glob(os.path.join(indir, '*.json'))
                   if not f.endswith('_manifest.json'))
    for f in files:
        bk = json.load(open(f, encoding='utf-8'))
        title = bk['book'].get('title')
        eng = build_book(bk, load_drift(title), load_protect(title), load_unknown(title))
        p = os.path.join(outdir, eng['book']['title'] + '.json')
        open(p, 'w', encoding='utf-8').write(json.dumps(eng, ensure_ascii=False, indent=2))

        nf = sum(len(v) for c in eng['characters'] for v in c['forms'].values())
        nc = sum(1 for c in eng['characters'] if c.get('_conflicts'))
        nd = sum(c.get('_drift', 0) for c in eng['characters'])
        nu = sum(1 for c in eng['characters'] if c.get('_source') == 'unknown')
        print('[engine] %-14s chars=%2d forms=%3d 家族=%d 去重跳过=%d 漂移并入=%d 保护词=%d 注册角色=%d' % (
            eng['book']['title'], len(eng['characters']), nf,
            len(eng['family_surnames']), nc, nd,
            len(eng.get('blacklist', [])) + len(eng.get('keep', [])), nu))
        for k, v in eng['family_surnames'].items():
            print('           %s -> %s' % (k, v))
    print('[engine] outdir=%s' % outdir)


if __name__ == '__main__':
    main(*(sys.argv[1:3] if len(sys.argv) > 1 else []))