#!/usr/bin/env python3
"""Check English, Chinese, or bilingual subtitles against the user's style.

Only the standard library is used so this runs anywhere Python is available.

    python check_style.py subtitles.ass
    python check_style.py subtitles.srt --verbose
"""

import argparse
import re
import sys

TAG = re.compile(r"\{[^}]*\}")
HAN = re.compile(r"[\u4e00-\u9fff]")
ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[.:](\d{2})")
SRT_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})")
HALF_PUNCT = re.compile(r"(?<=[\u4e00-\u9fff])[,.;:!?](?=[\u4e00-\u9fff]|\s|$)")
END_PUNCT = "。，；：,;:"
# Issues that follow from "one sentence per cue, never split a sentence".
# They are expected in that workflow and only mean the cue is a candidate for
# manual splitting, so they are reported apart from real defects.
SOFT_ISSUE = re.compile(
    r"单行.*超过|长于|短于|阅读速度|中文句尾用了标点|"
    r"中文之间混入半角标点|省略号"
)

MAX_CHARS = 26
MAX_LINES = 2
MIN_DUR = 0.8
MAX_DUR = 9.0
MAX_CPS = 9.0
NOTE_MAX_DUR = 12.0

# English cues in this workflow come from local transcription: one line of up
# to 42 characters reads comfortably, and 20 characters per second is the
# usual upper bound for Latin script.
ENG_MAX_CHARS = 85
ENG_MAX_CPS = 20.0
ENG_MIN_DUR = 1.0
ENG_MAX_DUR = 8.0


def to_seconds(m):
    h, mi, s, frac = m.groups()
    frac = float("0." + frac) if len(frac) == 3 else float("0." + frac)
    return int(h) * 3600 + int(mi) * 60 + int(s) + frac


def parse_ass(path):
    cues, section, fields = [], None, None
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith("["):
                section = line.strip("[]").lower()
                continue
            if section != "events":
                continue
            if line.startswith("Format:"):
                fields = [x.strip() for x in line.split(":", 1)[1].split(",")]
            elif line.startswith("Dialogue:") and fields:
                parts = line.split(":", 1)[1].split(",", len(fields) - 1)
                d = dict(zip(fields, parts))
                sm, em = ASS_TIME.search(d.get("Start", "")), ASS_TIME.search(d.get("End", ""))
                if sm and em:
                    cues.append((to_seconds(sm), to_seconds(em), d.get("Text", ""),
                                 d.get("Style", "")))
    return cues


def parse_srt(path):
    cues = []
    blocks = re.split(r"\n\s*\n", open(path, encoding="utf-8-sig", errors="replace").read())
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        tm = re.findall(SRT_TIME, lines[1]) if "-->" in lines[1] else None
        spans = re.findall(r"(\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{3})", b)
        if not spans:
            continue
        s, e = spans[0]
        text = "\n".join(lines[2:])
        cues.append((to_seconds(SRT_TIME.search(s)), to_seconds(SRT_TIME.search(e)), text, ""))
    return cues


def is_note_cue(cue):
    plain = TAG.sub("", cue[2]).strip()
    style = cue[3].lower()
    return (
        plain.startswith("*")
        or "upperleft" in style
        or "translator" in style
        or "note" in style
    )


def check(cue, idx):
    start, end, text, style = cue
    plain = TAG.sub("", text)
    lines = [l.strip() for l in plain.replace("\\N", "\n").replace("\\n", "\n").split("\n") if l.strip()]
    body = "".join(lines)
    # Translator notes are commentary, not subtitles: length and punctuation
    # rules do not apply to them.
    is_note = body.lstrip().startswith("*")
    dur = end - start
    han = len(HAN.findall(body))
    issues = []
    if is_note:
        if dur > NOTE_MAX_DUR:
            issues.append(f"注释时长 {dur:.2f}s 过长")
        if re.search(r"\s{2,}", plain.replace("\\N", "")):
            issues.append("有多余连续空格")
        return issues

    if len(lines) > MAX_LINES:
        issues.append(f"{len(lines)} 行，超过 {MAX_LINES} 行上限")

    line_info = []
    for pos, line in enumerate(lines):
        zh = len(HAN.findall(line))
        en = len(re.findall(r"[A-Za-z]", line))
        line_info.append((pos, line, zh, en))
    zh_lines = [item for item in line_info if item[2] >= item[3] and item[2] > 0]
    en_lines = [item for item in line_info if item[3] > item[2]]
    bilingual = bool(zh_lines and en_lines)

    if bilingual and zh_lines[0][0] > en_lines[0][0]:
        issues.append("双语顺序错误，应为中文在上、英文在下")

    for _, line, zh, en in line_info:
        if en > zh:
            n_chars = len(re.sub(r"\s", "", line))
            if n_chars > ENG_MAX_CHARS:
                issues.append(f"英文单行 {n_chars} 字符，超过 {ENG_MAX_CHARS} 字符上限")
            if dur > 0 and n_chars / dur > ENG_MAX_CPS:
                issues.append(
                    f"英文阅读速度 {n_chars / dur:.1f} 字符/秒，超过 {ENG_MAX_CPS}"
                )
        else:
            if zh > MAX_CHARS:
                issues.append(f"中文单行 {zh} 字，超过 {MAX_CHARS} 字常规范围")
            if dur > 0 and zh / dur > MAX_CPS:
                issues.append(f"中文阅读速度 {zh / dur:.1f} 字/秒，超过 {MAX_CPS}")

    min_dur = min(MIN_DUR, ENG_MIN_DUR) if bilingual else (
        ENG_MIN_DUR if en_lines else MIN_DUR
    )
    max_dur = max(MAX_DUR, ENG_MAX_DUR) if bilingual else (
        ENG_MAX_DUR if en_lines else MAX_DUR
    )
    if dur < min_dur:
        issues.append(f"时长 {dur:.2f}s，短于 {min_dur}s")
    if dur > max_dur:
        issues.append(f"时长 {dur:.2f}s，长于 {max_dur}s")

    chinese_text = "".join(item[1] for item in zh_lines)
    if chinese_text and chinese_text[-1] in END_PUNCT:
        issues.append(f"中文句尾用了标点“{chinese_text[-1]}”，本风格通常不加")
    if "…" in chinese_text:
        issues.append("用了省略号符号 …，本风格直接敲点")
    if HALF_PUNCT.search(chinese_text):
        issues.append("中文之间混入半角标点")
    if re.search(r"\s{2,}", plain.replace("\\N", "")):
        issues.append("有多余连续空格")
    if plain != plain.strip():
        issues.append("文本首尾有多余空格")
    if re.search(r"(?<!\.)\.{1,2}(?!\.)", chinese_text):
        issues.append("省略号点数少于 3 个")
    if style and style.strip().lower() not in ("default", ""):
        pass
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # A ".bak" beside a subtitle is still that subtitle; look past it.
    name = re.sub(r"\.bak$", "", args.path.lower())
    cues = parse_ass(args.path) if name.endswith((".ass", ".ssa")) else parse_srt(args.path)
    if not cues:
        print("没有解析到字幕条目")
        return 1

    # Overlapping cues are always a defect: two lines are asked to render at
    # the same moment, so the viewer sees one replace the other at random.
    overlaps = []
    primary = sorted(
        ((i, cue) for i, cue in enumerate(cues) if not is_note_cue(cue)),
        key=lambda item: (item[1][0], item[1][1]),
    )
    if primary:
        active_idx, active = primary[0]
        for current_idx, current in primary[1:]:
            if current[0] < active[1] - 0.001:
                overlaps.append((current_idx, current[0] - active[1]))
            if current[1] > active[1]:
                active_idx, active = current_idx, current

    total = len(cues)
    hard, soft = [], []
    for i, cue in enumerate(cues, 1):
        issues = check(cue, i)
        for idx, delta in overlaps:
            if idx == i - 1:
                issues.append(f"与上一条重叠 {abs(delta):.2f}s")
        if not issues:
            continue
        real = [x for x in issues if not SOFT_ISSUE.search(x)]
        if real:
            hard.append((i, real))
        if len(real) != len(issues):
            soft.append(i)
        if args.verbose:
            t = f"{cue[0]:.2f}"
            print(f"[{t:>8}s] {'; '.join(issues)}")
            print(f"          {TAG.sub('', cue[2])[:70]}")

    kinds = {}
    for _, issues in hard:
        for it in issues:
            key = re.sub(r"[\d.]+", "N", it)
            kinds[key] = kinds.get(key, 0) + 1
    print(f"条目 {total} 条")
    print(f"必须修正：{len(hard)} 条" + ("（无）" if not hard else ""))
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"  {v:>4}  {k}")
    if soft:
        print(f"待人工复核：{len(soft)} 条涉及长度、速度、时长或标点风格 —— "
              "不一定是缺陷，不必为消除提示而破坏语义")
    if overlaps:
        print(f"时间轴重叠：{len(overlaps)} 处（必须修掉，会导致字幕错位）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
