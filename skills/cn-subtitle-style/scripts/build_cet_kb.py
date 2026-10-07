#!/usr/bin/env python3
"""Rebuild the CET-4/CET-6 knowledge base from the upstream word lists.

Downloads the source lists on first use, caches them next to this script, and
writes `assets/cet_vocab.json` plus `assets/common_words.json`.

    python build_cet_kb.py
"""

import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.normpath(os.path.join(HERE, "..", "assets"))
CACHE = os.path.join(HERE, "cet_sources")

BASE = "https://raw.githubusercontent.com/Kaiyiwing/qwerty-learner/master/public/dicts/"

# Exam vocabulary, split by the level each list represents.
CET4_FILES = ["CET4_T.json", "xinghuoqiaoji_4.json", "Level4luan_2_T.json"]
CET6_FILES = ["CET6_T.json", "xinghuoqiaoji_6.json"]
# Word lists whose contents count as already-common vocabulary. Drop
# "GaoKao_3500.json" here to highlight far more words.
COMMON_FILES = ["top2000words.json", "GaoKao_3500.json", "Oxford3000.json"]
# Concise glosses come first; 星火 entries carry part-of-speech detail.
PREFERRED = ["CET4_T.json", "CET6_T.json"] + CET4_FILES + CET6_FILES

# Grammar words every learner already knows. Some are missing from the
# frequency lists, and highlighting "my" or "them" is pure noise.
FUNCTION_WORDS = """
a an the this that these those my your his her its our their me you him us them
mine yours myself yourself himself herself itself ourselves themselves
who whom whose which what someone anyone everyone something anything everything
nothing somebody anybody everybody nobody one ones other others another such
in on at by for with about into over under above below between among through
during before after to from of up down off out near behind beside across along
and but or nor so yet if because although though while when since unless until
as than whether both either neither
be am is are was were been being have has had having do does did doing done
will would shall should can could may might must ought
not no yes very too also just only still even ever never always often sometimes
usually again here there now then well quite rather almost enough already soon
maybe together away back own same each every all any some few many much more
most less least
one two three four five six seven eight nine ten first second third
hundred thousand million
""".split()


def fetch(name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        print(f"  downloading {name}")
        req = urllib.request.Request(BASE + name, headers={"User-Agent": "codex"})
        with urllib.request.urlopen(req, timeout=60) as r:
            open(path, "wb").write(r.read())
    return path


def load(name):
    out = {}
    for item in json.load(open(fetch(name), encoding="utf-8")):
        w = (item.get("name") or "").strip()
        if not w or not w.isascii():
            continue
        out[w.lower()] = {
            "word": w,
            "trans": [t for t in (item.get("trans") or []) if t],
            "us": item.get("usphone") or "",
            "uk": item.get("ukphone") or "",
        }
    return out


def main():
    src = {name: load(name) for name in PREFERRED}
    c4, c6 = set(), set()
    for name in CET4_FILES:
        c4 |= set(src.get(name, {}))
    for name in CET6_FILES:
        c6 |= set(src.get(name, {}))

    kb = {}
    for w in sorted(c4 | c6):
        entry = {"level": "四级" if w in c4 else "六级"}
        if w in c4 and w in c6:
            entry["level"] = "四级/六级"
        for name in PREFERRED:
            item = src.get(name, {}).get(w)
            if item and item["trans"]:
                entry.update(word=item["word"], trans=item["trans"],
                             us=item["us"], uk=item["uk"], source=name)
                break
        if "trans" not in entry:
            continue
        if all(t.strip() in ("找不到解释", "") for t in entry["trans"]):
            continue
        kb[w] = entry

    common = set()
    for name in COMMON_FILES:
        common |= set(load(name))
    common |= set(FUNCTION_WORDS)
    common &= set(kb)

    os.makedirs(ASSETS, exist_ok=True)
    json.dump(kb, open(os.path.join(ASSETS, "cet_vocab.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(sorted(common),
              open(os.path.join(ASSETS, "common_words.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"四六级词表 {len(kb)} 词，常用词 {len(common)} 词，"
          f"实际可标红 {len(kb) - len(common)} 词")


if __name__ == "__main__":
    main()
