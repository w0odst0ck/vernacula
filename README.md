# Vernacula

**Localize foreign character names in fiction.**

Read a Russian novel without losing track of who's who.

[中文说明](README.zh-CN.md)

```
Родион Романович Раскольников  →  罗景行
Raskolnikov                    →  罗景行
Rodion                         →  罗景行
Rodya                          →  景行
```

Same person. Native name. Original text untouched.

---

## Why

Long transliterated names break reading flow:

> *Rodion Romanovich Raskolnikov*, *Arkady Ivanovich Svidrigailov*,
> *Pulcheria Alexandrovna* — by chapter three you've lost track.

Vernacula swaps just the names. Everything else — places, institutions,
author names — stays exactly as written.

---

## Design principles

### Only names change

`Petersburg` stays `Petersburg`. So do institutions, streets, and authors.

### Register for register

Chinese has multiple ways to address one person — formal given name,
familiar nickname, childhood pet name. Vernacula preserves that layering
instead of collapsing everything into one string.

| Original | Register | Localized |
|---|---|---|
| Raskolnikov | surname (formal/narrative) | 罗景行 |
| Rodion | given name | 罗景行 |
| Rodya | nickname | 景行 |
| Rodechka | affectionate | 小景 |

### Patronymics dissolve

Russian names are `given · patronymic · surname`. Chinese has no patronymic.

The engine parses the whole name string as a structure and collapses it:

```
Rodion Romanovich Raskolnikov  →  罗景行
```

Not word-by-word substitution.

### When unsure, keep the original

Unregistered names pass through untouched. Better to under-localize than
to swap the wrong person.

### Chapter by chapter

Not one batch run over a whole book.

Translate a chapter → read it → give feedback → refine the lexicon →
next chapter. The rules grow from reading, not from upfront design.

---

## Status

**Early development.** Working today:

- Full-name structure parsing and patronymic dissolution
- Separator tolerance (`·` / `-` / whitespace)
- Transliteration drift adaptation (spelling variants across editions)
- Proper-noun protection (place names won't be mangled)
- Chapter segmentation and per-chapter annotation

**In progress:**

- Chapter-level pipeline with iterative review
- Structural name parser (replacing literal matching)
- Interactive feedback workflow

---

## Quick start

```bash
git clone https://github.com/w0odst0ck/vernacula.git
cd vernacula
```

Python 3.9+, no third-party dependencies.

### Define your mapping

```bash
cp names/maps/_template.json names/maps/yourbook.json
```

```json
{
  "book": { "title": "Crime and Punishment" },
  "characters": [
    {
      "hanhua": "罗景行",
      "role": "protagonist",
      "localize": {
        "full": "罗景行",
        "surname": "罗",
        "nickname": "景行"
      },
      "forms": {
        "surname": ["Raskolnikov"],
        "given": ["Rodion"],
        "nickname": ["Rodya"]
      }
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `localize` | Chinese forms (full / surname / given / nickname) |
| `forms` | Source-language forms (surname / given / patronymic / nickname) |

### Run

```bash
python tools/build_engine.py       # mapping → engine config
python tools/run_all.py --skip-sync # render output
```

---

## Layout

```
vernacula/
├─ localize_names.py      name localization engine
├─ tools/
│  ├─ build_engine.py     mapping → engine config
│  ├─ drift.py            transliteration drift detection
│  ├─ protect.py          proper-noun damage detection
│  ├─ unknown.py          unregistered character discovery
│  └─ run_all.py          batch rendering
└─ names/
   ├─ maps/               character mappings
   ├─ drift/              spelling variants across editions
   ├─ protect/            place names and author names
   ├─ unknown/            minor characters found while reading
   └─ engine/             generated engine config
```

### Four independent layers

| Layer | Responsibility | When to edit |
|---|---|---|
| **maps** | Who is who, what they're called | New character, rename |
| **drift** | Spelling differences across editions | Switching to a different edition |
| **protect** | Place names, author names | When damage is detected |
| **unknown** | Minor characters | When you meet one while reading |

Each layer is independent. Swap editions → edit drift only.
Find damage → edit protect only.

---

## Copyright

**This project contains no novel text.**

You supply your own legally obtained source files.

Character-name mappings are factual data (forms of address) and contain no
prose from the works themselves.

---

## The name

**vernacula** (Latin) — native, home-born
**vernacular** — the language of one's own country

*Make names that don't belong here belong.*

---

## License

MIT — see [LICENSE](LICENSE).

---

<details>
<summary>中文说明</summary>

## 中文说明

把外国小说里的人名，换成本土的名字。读起来，像一本本国的小说。

完整中文文档：[README.zh-CN.md](README.zh-CN.md)

**核心原则：**

- 只动人名，地名、机构名、作者名一律保留
- 语域对语域——正式称呼、昵称、爱称各有其位，不强行归一
- 父称消解——俄式三段姓名整体识别，中文里合成一个名字
- 不确定就不换——未注册的人名原样保留
- 逐章迭代——读一章、改一章、长一章词库

**四层分离：**

| 层 | 职责 | 何时改 |
|---|---|---|
| maps | 人物是谁、叫什么 | 新增人物、改名 |
| drift | 不同译本的用字差异 | 换版次时 |
| protect | 含人名的地名、作者名 | 发现误伤时 |
| unknown | 表外小配角 | 阅读中遇到时 |

**不含任何小说原文。** 请自行准备合法获得的文本。

</details>