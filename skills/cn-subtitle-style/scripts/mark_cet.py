#!/usr/bin/env python3
"""Mark CET-4/CET-6 words in English subtitles and report where they appear.

Everyday words are excluded using the companion common-word list, otherwise
roughly half of all subtitle words light up and the highlight means nothing.

    python mark_cet.py --item video1.en.ass video1.words.json video1 \
                       --item video2.en.ass video2.words.json video2 \
                       --out-dir ../outputs

Each input pair is an .ass subtitle file plus the word-level transcript JSON
produced by `transcribe.py --dump-json`. Writes `<name>.cet.ass` with matched
words in red, plus a Markdown and a CSV report.
"""

import argparse
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
KB_PATH = os.path.join(ASSETS, "cet_vocab.json")
COMMON_PATH = os.path.join(ASSETS, "common_words.json")

RED = r"{\c&H0000FF&}"
WHITE = r"{\c&HFFFFFF&}"
TOKEN = re.compile(r"[A-Za-z][A-Za-z']*")
RED_OPEN = re.compile(r"\{\\c&H0000FF&\}")

# Past and participle forms the suffix rules cannot recover.
IRREGULAR = {
    "was": "be", "were": "be", "is": "be", "are": "be", "am": "be",
    "been": "be", "being": "be", "has": "have", "had": "have", "having": "have",
    "does": "do", "did": "do", "done": "do", "doing": "do",
    "went": "go", "gone": "go", "goes": "go", "said": "say", "made": "make",
    "took": "take", "taken": "take", "came": "come", "saw": "see", "seen": "see",
    "got": "get", "gotten": "get", "knew": "know", "known": "know",
    "thought": "think", "gave": "give", "given": "give", "found": "find",
    "told": "tell", "became": "become", "felt": "feel", "brought": "bring",
    "began": "begin", "begun": "begin", "kept": "keep", "held": "hold",
    "wrote": "write", "written": "write", "stood": "stand", "heard": "hear",
    "meant": "mean", "met": "meet", "ran": "run", "paid": "pay", "sat": "sit",
    "spoke": "speak", "spoken": "speak", "led": "lead", "grew": "grow",
    "grown": "grow", "lost": "lose", "fell": "fall", "fallen": "fall",
    "sent": "send", "built": "build", "understood": "understand",
    "drew": "draw", "drawn": "draw", "broke": "break", "broken": "break",
    "spent": "spend", "rose": "rise", "risen": "rise", "drove": "drive",
    "driven": "drive", "bought": "buy", "wore": "wear", "worn": "wear",
    "chose": "choose", "chosen": "choose", "ate": "eat", "eaten": "eat",
    "drank": "drink", "drunk": "drink", "sang": "sing", "sung": "sing",
    "swam": "swim", "swum": "swim", "taught": "teach", "caught": "catch",
    "threw": "throw", "thrown": "throw", "flew": "fly", "flown": "fly",
    "forgot": "forget", "forgotten": "forget", "forgave": "forgive",
    "forgiven": "forgive", "hid": "hide", "hidden": "hide", "won": "win",
    "woke": "wake", "woken": "wake", "slept": "sleep", "swept": "sweep",
    "sought": "seek", "sold": "sell", "shook": "shake", "shaken": "shake",
    "shone": "shine", "shot": "shoot", "shown": "show", "sank": "sink",
    "sunk": "sink", "stole": "steal", "stolen": "steal", "stuck": "stick",
    "struck": "strike", "swore": "swear", "sworn": "swear", "tore": "tear",
    "torn": "tear", "wept": "weep", "hung": "hang", "fought": "fight",
    "dug": "dig", "laid": "lay", "wound": "wind", "froze": "freeze",
    "frozen": "freeze", "sprang": "spring", "stung": "sting",
}


def build_resolver(kb):
    def candidates(word):
        yield word
        irr = IRREGULAR.get(word)
        if irr:
            yield irr
        if len(word) > 3 and word.endswith("ies"):
            yield word[:-3] + "y"
        if len(word) > 3 and word.endswith("es"):
            yield word[:-2]
        if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
            yield word[:-1]
        if len(word) > 3 and word.endswith("ied"):
            yield word[:-3] + "y"
        if len(word) > 3 and word.endswith("ed"):
            yield word[:-2]
            yield word[:-1]
            if len(word) > 4 and word[-3] == word[-4]:
                yield word[:-3]
        if len(word) > 4 and word.endswith("ing"):
            stem = word[:-3]
            yield stem
            yield stem + "e"
            if len(stem) > 2 and stem[-1] == stem[-2]:
                yield stem[:-1]
        # No -er/-est stripping: it turns "master" into "mast".
        if len(word) > 4 and word.endswith("ly"):
            yield word[:-2]

    def resolve(token):
        # Transcript tokens carry a leading space and often trailing
        # punctuation, so reduce to the alphabetic core first.
        w = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", token).lower()
        if not w:
            return None
        for c in candidates(w):
            if c in kb:
                return c
        return None

    return resolve


def highlight(text, resolve):
    def repl(m):
        tok = m.group(0)
        return f"{RED}{tok}{WHITE}" if resolve(tok) else tok

    return TOKEN.sub(repl, text)


def existing_red_words(path):
    """Words already painted red in a subtitle file.

    The user's own marks are the source of truth: re-deriving them from the
    vocabulary list would silently undo any manual adjustment.
    """
    out = set()
    for line in open(path, encoding="utf-8-sig"):
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = parts[9]
        for m in RED_OPEN.finditer(text):
            seg = text[m.end():]
            cut = seg.find("{")
            if cut != -1:
                seg = seg[:cut]
            for tok in TOKEN.findall(seg):
                w = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", tok).lower()
                if w:
                    out.add(w)
    return out


def exact_resolver(words):
    def resolve(token):
        w = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", token).lower()
        return w if w in words else None

    return resolve


def load_words(path):
    out = []
    for seg in json.load(open(path, encoding="utf-8")):
        for w in seg.get("words") or []:
            if w.get("start") is not None:
                out.append((float(w["start"]), w["word"]))
    return out


def read_cues(path):
    cues = []
    for line in open(path, encoding="utf-8-sig").read().splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)      # the Text field may contain commas
        if len(parts) < 10:
            continue
        h, m, s = parts[1].split(":")
        cues.append((int(h) * 3600 + int(m) * 60 + float(s),
                     parts[9].replace("\\N", " ").strip()))
    return cues


def fmt(t):
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def process(label, ass_in, words_in, resolve, kb, out_dir):
    lines, cue_list = [], read_cues(ass_in)
    for line in open(ass_in, encoding="utf-8-sig").read().splitlines():
        if line.startswith("Dialogue:"):
            head, sep, text = line.rpartition(",,")
            line = f"{head}{sep}{highlight(text, resolve)}"
        lines.append(line)
    ass_out = os.path.join(out_dir, f"{label}.cet.ass")
    open(ass_out, "w", encoding="utf-8-sig").write("\n".join(lines) + "\n")

    occ = []
    for t, token in load_words(words_in):
        base = resolve(token)
        if not base:
            continue
        cue = ""
        for cs, ct in cue_list:
            if cs <= t:
                cue = ct
            else:
                break
        occ.append({
            "video": label, "time": t, "word": base,
            "form": re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", token),
            "cue": cue,
        })
    return ass_out, occ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", nargs=3, action="append", required=True,
                    metavar=("ASS", "WORDS_JSON", "LABEL"),
                    help="subtitle file, word-level transcript, output label")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--marks-from", default=None,
                    help="carry the red marks already present in this subtitle "
                         "file instead of recomputing them from the vocabulary")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore existing marks and re-detect from the vocabulary")
    args = ap.parse_args()

    kb = json.load(open(KB_PATH, encoding="utf-8"))
    common = set(json.load(open(COMMON_PATH, encoding="utf-8")))
    kb = {k: v for k, v in kb.items() if k not in common}

    # Prefer marks that already exist in the file; only fall back to detecting
    # from the vocabulary when there are none.
    carry, source = set(), None
    if not args.refresh:
        if args.marks_from:
            carry = existing_red_words(args.marks_from)
            source = args.marks_from
        else:
            for ass, _, _ in args.item:
                got = existing_red_words(ass)
                if got:
                    carry |= got
                    source = source or ass
    if carry:
        resolve = exact_resolver(carry)
        print(f"沿用已有标红 {len(carry)} 个单词（来自 {os.path.basename(source)}）")
    else:
        resolve = build_resolver(kb)
        print("文件里没有标红标记，按知识库检测")
    os.makedirs(args.out_dir, exist_ok=True)

    all_occ, per_label, made = [], [], []
    for ass, words, label in args.item:
        ass_out, occ = process(label, ass, words, resolve, kb, args.out_dir)
        made.append(ass_out)
        all_occ += occ
        per_label.append((label, len(occ)))

    counts = {}
    for o in all_occ:
        counts[o["word"]] = counts.get(o["word"], 0) + 1

    md = ["# 视频中的四六级词汇", "",
          f"命中 {len(counts)} 个词，共出现 {len(all_occ)} 次。", "",
          "已排除常用词（高频词表、高考词汇、牛津 3000 及基础功能词），"
          "否则近半数的字幕词都会被标红。", "",
          "| 视频 | 命中次数 |", "|---|---|"]
    for label, c in per_label:
        md.append(f"| {label} | {c} |")
    for label, _ in per_label:
        md += ["", f"## {label} 出现明细", "",
               "| 时间 | 单词 | 级别 | 释义 | 所在字幕 |", "|---|---|---|---|---|"]
        for o in all_occ:
            if o["video"] != label:
                continue
            e = kb[o["word"]]
            gloss = "；".join(e["trans"]).replace("|", "/")[:70]
            star = "" if o["form"].lower() == o["word"] else f"（{o['form']}）"
            md.append(f"| {fmt(o['time'])} | {e.get('word', o['word'])}{star} | "
                      f"{e['level']} | {gloss} | {o['cue'].replace('|', '/')[:60]} |")
    md += ["", "## 去重词汇表", "",
           "| 单词 | 级别 | 音标 | 释义 | 出现次数 |", "|---|---|---|---|---|"]
    for w, c in sorted(counts.items(), key=lambda x: -x[1]):
        e = kb[w]
        md.append(f"| {e.get('word', w)} | {e['level']} | {e.get('us','')} | "
                  f"{'；'.join(e['trans']).replace('|', '/')} | {c} |")

    md_path = os.path.join(args.out_dir, "cet-words-in-videos.md")
    open(md_path, "w", encoding="utf-8").write("\n".join(md) + "\n")
    csv_path = os.path.join(args.out_dir, "cet-words-in-videos.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["video", "time", "word", "form", "level", "meaning", "cue"])
        for o in all_occ:
            e = kb[o["word"]]
            wr.writerow([o["video"], fmt(o["time"]), e.get("word", o["word"]),
                         o["form"], e["level"], "；".join(e["trans"]), o["cue"]])

    print(f"命中 {len(counts)} 个词 / {len(all_occ)} 次")
    for label, c in per_label:
        print(f"   {label}: {c} 次")
    for p in made:
        print("  ", p)
    print("  ", md_path)


if __name__ == "__main__":
    main()
