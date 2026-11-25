#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
run_all.py — 一键出全部成品
==========================
流程：人名映射表.xlsx --(x2j)--> names/maps --(build_engine)--> names/engine --(localize)--> output/

用法：
  py -X utf8 tools/run_all.py              # 全流程
  py -X utf8 tools/run_all.py --skip-sync  # 跳过表同步（直接用现有 engine 配置）
"""
import os, sys, json, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))

from mapctl import cmd_x2j, DEFAULT_XLSX, DEFAULT_JSONDIR
from build_engine import main as build_main
from localize_names import localize

# 书名 -> 正文文件名
NOVELS = {}
for f in glob.glob('*.txt'):
    for k in ('卡拉马佐夫兄弟', '静静的顿河', '罪与罚', '白痴', '愤怒的葡萄'):
        if f.startswith(k):
            NOVELS[k] = f

OUTDIR = 'output'
# 输出单一模式：C2 = 按章首见标注（方括号）
OUT_MODE = 'C2'
OUT_BRACKETS = '[]'
OUT_SUFFIX = '_汉化版.txt'


def main(skip_sync=False):
    if not skip_sync:
        print('== [1/3] 表 -> JSON ==')
        cmd_x2j(DEFAULT_XLSX, DEFAULT_JSONDIR)

    print('== [2/3] JSON -> 引擎配置 ==')
    build_main()

    print('== [3/3] 出成品 ==')
    os.makedirs(OUTDIR, exist_ok=True)
    # 清理旧的双模式产物（纯汉化 / 首见标注），避免混淆
    for old in glob.glob(os.path.join(OUTDIR, '*_汉化版（*.txt')):
        os.remove(old)
        print('   清理旧文件 %s' % os.path.basename(old))
    for name in sorted(NOVELS):
        eng_path = os.path.join('names', 'engine', name + '.json')
        if not os.path.exists(eng_path):
            print('   跳过 %s（无引擎配置）' % name)
            continue
        text = open(NOVELS[name], 'rb').read().decode('utf-8-sig')
        eng = json.load(open(eng_path, encoding='utf-8'))
        doc = json.loads(json.dumps(eng))
        doc['mode'] = OUT_MODE
        doc['brackets'] = OUT_BRACKETS
        new, cnt, conf = localize(text, doc)
        out = os.path.join(OUTDIR, name + OUT_SUFFIX)
        open(out, 'w', encoding='utf-8').write(new)
        print('   %-12s 模式%s 替换%d处  ->  %s' % (
            name, OUT_MODE, sum(cnt.values()), os.path.basename(out)))


if __name__ == '__main__':
    main(skip_sync='--skip-sync' in sys.argv)