#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
mapctl.py — 人名映射表 ⇄ JSON 双向维护工具
=========================================
设计：xlsx 给人看/给人改，JSON 给机器用；两边都能改，靠本工具同步。

用法
----
  py -X utf8 mapctl.py x2j   [xlsx] [outdir]     # 表 → JSON
  py -X utf8 mapctl.py j2x   [jsondir] [xlsx]    # JSON → 表（默认写新文件；--force 覆盖）
  py -X utf8 mapctl.py check [xlsx] [jsondir]    # 一致性校验，报告漂移

约定
----
· 一张表可含多本书（多 sheet），每 sheet 内分若干「分组」（每 3 列一组）
· 首行写分组标题；第二行固定表头：原译名 | 汉化名 | 备注
· 备注里的本土化线索自动解析：
    昵称/外号/绰号"X" → nickname     小名/乳名"X" → petname
    爱称"X"            → intimate    称"X"        → alias
    即X                → aka（正文实际使用的原形，匹配的关键桥梁）
"""
import sys, os, re, json, glob, hashlib

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

DEFAULT_XLSX = '人名映射表.xlsx'
DEFAULT_JSONDIR = os.path.join('names', 'maps')
DEFAULT_REBUILT = '人名映射表_rebuilt.xlsx'
STATE_FILE = os.path.join('names', '.sync_state.json')

GROUP_W = 3
HEADERS = ('原译名', '汉化名', '备注')

TAG_RE = re.compile(r'(昵称|小名|乳名|爱称|外号|绰号|别称|称作|称)[“"]([^”"]+)[”"]')
KIND = {'昵称': 'nickname', '小名': 'petname', '乳名': 'petname', '爱称': 'intimate',
        '外号': 'nickname', '绰号': 'nickname', '别称': 'alias', '称作': 'alias', '称': 'alias'}
AKA_RE = re.compile(r'即([\u4e00-\u9fff·]{2,8}?)(?=[，。；、（(]|$)')
PAREN_RE = re.compile(r'[（(]([^）)]+)[）)]')


def md5(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def parse_note(note):
    """从备注里挖本土化线索"""
    out = {'aka': [], 'nickname': [], 'petname': [], 'intimate': [], 'alias': []}
    if not note:
        return out
    for kind, val in TAG_RE.findall(note):
        out[KIND[kind]].append(val.strip())
    for m in AKA_RE.findall(note):
        out['aka'].append(m.strip())
    for k in out:
        seen = set()
        out[k] = [x for x in out[k] if x and not (x in seen or seen.add(x))]
    return out


def split_origin(s):
    """原译名 -> (主要片段, 括号内变体)"""
    if not s:
        return [], []
    inner = [x.strip() for x in PAREN_RE.findall(s)]
    s2 = PAREN_RE.sub('', s)
    parts = [p.strip() for p in re.split(r'[·\-]', s2) if p.strip()]
    return parts, inner


def read_xlsx(path):
    wb = openpyxl.load_workbook(path)
    books = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            continue
        r1 = rows[0]
        starts = [i for i, v in enumerate(r1) if v is not None and str(v).strip()]
        groups = []
        for gi, si in enumerate(starts):
            def get(row, i):
                return row[i] if i < len(row) else None
            chars = []
            for row in rows[2:]:
                origin, hanhua, note = get(row, si), get(row, si + 1), get(row, si + 2)
                if not (origin or hanhua):
                    continue
                origin = str(origin).strip() if origin else ''
                hanhua = str(hanhua).strip() if hanhua else ''
                note = str(note).strip() if note else ''
                parts, inner = split_origin(origin)
                chars.append({
                    'origin': origin, 'hanhua': hanhua, 'note': note,
                    'forms': dict({'origin_parts': parts, 'origin_inner': inner}, **parse_note(note)),
                })
            groups.append({'index': gi + 1, 'title': str(r1[si]).strip(), 'characters': chars})
        books.append({
            'schema_version': '3.0',
            'book': {'id': ws.title, 'title': ws.title, 'sheet': ws.title,
                     'source': os.path.basename(path)},
            'groups': groups,
        })
    return books


def write_xlsx(books, path):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    hdr_font = Font(bold=True, size=11)
    grp_font = Font(bold=True, size=12, color='1F4E79')
    fill = PatternFill('solid', fgColor='DDEBF7')
    for bk in books:
        title = (bk['book'].get('sheet') or bk['book'].get('title') or 'Sheet')[:31]
        ws = wb.create_sheet(title)
        groups = bk['groups']
        for gi, g in enumerate(groups):
            c = ws.cell(row=1, column=gi * GROUP_W + 1, value=g['title'])
            c.font = grp_font
        for gi in range(len(groups)):
            for ci, h in enumerate(HEADERS):
                c = ws.cell(row=2, column=gi * GROUP_W + ci + 1, value=h)
                c.font = hdr_font
                c.fill = fill
                c.alignment = Alignment(horizontal='center')
        maxn = max([len(g['characters']) for g in groups] or [1])
        for ri in range(maxn):
            for gi, g in enumerate(groups):
                if ri >= len(g['characters']):
                    continue
                ch = g['characters'][ri]
                base = gi * GROUP_W + 1
                ws.cell(row=ri + 3, column=base, value=ch['origin'])
                ws.cell(row=ri + 3, column=base + 1, value=ch['hanhua'])
                ws.cell(row=ri + 3, column=base + 2, value=ch.get('note', ''))
        for gi in range(len(groups)):
            ws.column_dimensions[get_column_letter(gi * GROUP_W + 1)].width = 32
            ws.column_dimensions[get_column_letter(gi * GROUP_W + 2)].width = 12
            ws.column_dimensions[get_column_letter(gi * GROUP_W + 3)].width = 30
        ws.freeze_panes = 'A3'
    wb.save(path)


def canon(bk):
    """规范化（只保留往返必需字段），用于一致性比较"""
    return {
        'title': bk['book'].get('sheet') or bk['book'].get('title'),
        'groups': [
            {'title': g['title'],
             'chars': [[c['origin'], c['hanhua'], c.get('note', '')] for c in g['characters']]}
            for g in bk['groups']
        ],
    }


def load_jsons(jsondir):
    books = []
    order = []
    mf = os.path.join(jsondir, '_manifest.json')
    if os.path.exists(mf):
        order = json.load(open(mf, encoding='utf-8')).get('order', [])
    files = [f for f in glob.glob(os.path.join(jsondir, '*.json')) if not f.endswith('_manifest.json')]
    for f in files:
        books.append(json.load(open(f, encoding='utf-8')))
    if order:
        rank = {t: i for i, t in enumerate(order)}
        books.sort(key=lambda b: rank.get(b['book'].get('title'), 999))
    else:
        books.sort(key=lambda b: b['book'].get('title', ''))
    return books


def cmd_x2j(xlsx, outdir):
    books = read_xlsx(xlsx)
    os.makedirs(outdir, exist_ok=True)
    for bk in books:
        p = os.path.join(outdir, bk['book']['title'] + '.json')
        open(p, 'w', encoding='utf-8').write(json.dumps(bk, ensure_ascii=False, indent=2))
    json.dump({'order': [b['book']['title'] for b in books]},
              open(os.path.join(outdir, '_manifest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    json.dump({'xlsx_md5': md5(xlsx),
               'json_md5': sorted(md5(os.path.join(outdir, b['book']['title'] + '.json')) for b in books)},
              open(STATE_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('[x2j] books=%d' % len(books))
    for bk in books:
        nc = sum(len(g['characters']) for g in bk['groups'])
        nf = sum(len(v) for g in bk['groups'] for c in g['characters'] for v in c['forms'].values())
        print('  %-16s groups=%d chars=%d forms=%d' % (bk['book']['title'], len(bk['groups']), nc, nf))
    print('[x2j] outdir=%s' % outdir)


def cmd_j2x(jsondir, out, force):
    books = load_jsons(jsondir)
    if os.path.exists(out) and not force:
        base, ext = os.path.splitext(out)
        out = base + '_new' + ext
        print('[j2x] target exists -> ' + out)
    write_xlsx(books, out)
    print('[j2x] books=%d -> %s' % (len(books), out))


def cmd_check(xlsx, jsondir):
    xb = {b['book']['title']: canon(b) for b in read_xlsx(xlsx)}
    jb = {b['book']['title']: canon(b) for b in load_jsons(jsondir)}
    lines = []
    ok = True
    for t in sorted(set(xb) | set(jb)):
        if t not in xb:
            lines.append('  [ONLY-JSON] %s' % t); ok = False; continue
        if t not in jb:
            lines.append('  [ONLY-XLSX] %s' % t); ok = False; continue
        a, b = xb[t], jb[t]
        if a == b:
            n = sum(len(g['chars']) for g in a['groups'])
            lines.append('  [SAME] %s chars=%d' % (t, n))
            continue
        ok = False
        lines.append('  [DIFF] %s' % t)
        ga = {g['title']: g['chars'] for g in a['groups']}
        gb = {g['title']: g['chars'] for g in b['groups']}
        for gt in sorted(set(ga) | set(gb)):
            ca, cb = ga.get(gt, []), gb.get(gt, [])
            if ca != cb:
                sa = {tuple(x) for x in ca}
                sb = {tuple(x) for x in cb}
                for x in sorted(sa - sb):
                    lines.append('    xlsx-only: %s' % (x,))
                for x in sorted(sb - sa):
                    lines.append('    json-only: %s' % (x,))
    st = ''
    if os.path.exists(STATE_FILE):
        s = json.load(open(STATE_FILE, encoding='utf-8'))
        st = 'xlsx_changed=%s' % (md5(xlsx) != s.get('xlsx_md5'))
    print('[check] in_sync=%s %s' % (ok, st))
    for l in lines:
        print(l)
    open('_mapctl_check.txt', 'w', encoding='utf-8').write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'check'
    args = [a for a in sys.argv[2:] if not a.startswith('--')]
    force = '--force' in sys.argv
    if cmd == 'x2j':
        cmd_x2j(args[0] if args else DEFAULT_XLSX, args[1] if len(args) > 1 else DEFAULT_JSONDIR)
    elif cmd == 'j2x':
        cmd_j2x(args[0] if args else DEFAULT_JSONDIR, args[1] if len(args) > 1 else DEFAULT_REBUILT, force)
    else:
        cmd_check(args[0] if args else DEFAULT_XLSX, args[1] if len(args) > 1 else DEFAULT_JSONDIR)