"""Build an English ASS draft from reviewed sentences and word timestamps.

The reviewed transcript is aligned to the recognition as one monotonic token
sequence. Local anchors are only a rescue for an unresolved region. Long
sentences are split at clause boundaries, preferring real pauses. The resulting
word times are a draft: waveform-aware refinement is still required before
final delivery.
"""

import argparse
import difflib
import json
import os
import re
import sys

os.environ.setdefault("PYTHONUTF8", "1")
sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import whisper_env  # noqa: E402

whisper_env.setup()

import pysubs2  # noqa: E402

import transcribe as T  # noqa: E402

ANCHOR_STEPS = (3, 4, 5, 6, 8, 12)
SEARCH_AHEAD = 400

# A cue is split only at the start of a clause, never inside a phrase. The
# list mirrors what the user's own subtitles break on: coordinating
# conjunctions, subordinators, and participial or prepositional openers.
CLAUSE_STARTERS = {
    "and", "but", "or", "nor", "so", "yet", "as", "with", "without", "because",
    "since", "when", "while", "then", "if", "though", "although", "before",
    "after", "until", "which", "who", "whose", "that", "where", "why", "how",
    "showing", "making", "turning", "leaving", "going", "coming", "being",
    "having", "doing", "meanwhile", "however", "instead", "still",
}

TARGET_CHARS = 47      # the user's own cues sit around here
MAX_CHARS = 85
MAX_DUR = 8.0
LEAD = 0.12            # how early a cue may appear when there is room
TAIL = 0.15            # how long it may linger after the last word
PAUSE_WEIGHT = 24.0    # prefer a real pause among equally valid clause cuts


def subtokens(tok):
    out = []
    for piece in re.findall(r"[a-z0-9']+", tok.lower()):
        piece = piece.strip("'")
        if piece:
            out.append(piece)
    return out


def load_sentences(paths):
    text = " ".join(open(p, encoding="utf-8").read().strip() for p in paths)
    text = re.sub(r"\s+", " ", text)
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    parts = [s if s.endswith((".", "!", "?")) else s + "." for s in parts]

    out = []
    for s in parts:
        words = s.split()
        subs, orig, sub2word = [], [], []
        for wi, w in enumerate(words):
            for st in subtokens(w):
                subs.append(st)
                orig.append(w)
                sub2word.append(wi)
        out.append({"text": s, "words": words, "subs": subs, "orig": orig,
                    "sub2word": sub2word})
    return out


def piece_text(sent, a, b):
    wa, wb = sent["sub2word"][a], sent["sub2word"][b]
    return " ".join(sent["words"][wa:wb + 1])


def load_recognition(path):
    rec = []
    for seg in json.load(open(path, encoding="utf-8")):
        for w in seg.get("words") or []:
            if w.get("start") is None or w.get("end") is None:
                continue
            for n in subtokens(w["word"]):
                rec.append({"start": float(w["start"]), "end": float(w["end"]),
                            "token": w["word"].strip(), "norm": n})
    rec.sort(key=lambda r: r["start"])
    return rec


def find_run(norms, pattern, lo, hi):
    n = len(pattern)
    if n == 0:
        return None
    hi = min(hi, len(norms) - n + 1)
    for i in range(max(lo, 0), hi):
        if norms[i:i + n] == pattern:
            return i
    return None


def locate(sentences, rec):
    """Locate every reviewed token in one monotonic global alignment.

    Exact sequence equality is the normal path because punctuation review must
    not change words. SequenceMatcher handles small recognition differences.
    Local anchors are only a rescue inside the expected forward window; they
    never search the whole transcript or move the cursor backwards.
    """
    norms = [r["norm"] for r in rec]
    flat, spans = [], []
    for s in sentences:
        start = len(flat)
        flat.extend(s["subs"])
        spans.append((start, len(flat)))

    mapping = {}
    if flat == norms:
        mapping = {i: i for i in range(len(flat))}
        mode = "exact"
    else:
        mode = "global-diff"
        matcher = difflib.SequenceMatcher(a=flat, b=norms, autojunk=False)
        for tag, a1, a2, b1, b2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(a2 - a1):
                    mapping[a1 + offset] = b1 + offset

    cursor, resolved, failures = 0, [], []
    for idx, s in enumerate(sentences):
        words = s["subs"]
        span_start, span_end = spans[idx]
        mapped = [mapping.get(i) for i in range(span_start, span_end)]
        if (mapped and all(i is not None for i in mapped)
                and mapped[0] >= cursor
                and all(b == a + 1 for a, b in zip(mapped, mapped[1:]))):
            resolved.append({
                "index": idx, "h": mapped[0], "last": mapped[-1],
                "anchor": "global",
            })
            cursor = mapped[-1] + 1
            continue

        hit = None
        whole = find_run(norms, words, cursor, cursor + SEARCH_AHEAD)
        if whole is not None:
            hit = (whole, whole + len(words) - 1, "full")
        for k in ANCHOR_STEPS:
            if hit:
                break
            kk = min(k, len(words))
            if kk < 1:
                continue
            head, tail = words[:kk], words[-kk:]
            window = min(SEARCH_AHEAD, 40 * kk)
            h = find_run(norms, head, cursor, cursor + window)
            if h is None:
                continue
            expected_tail = h + len(words) - kk
            t = find_run(
                norms, tail,
                max(h, expected_tail - 8),
                expected_tail + 9,
            )
            if t is None:
                continue
            hit = (h, t + kk - 1, kk)
            break
        if hit:
            h, last, k = hit
            resolved.append({"index": idx, "h": h, "last": last, "anchor": k})
            cursor = last + 1
        else:
            failures.append({"index": idx})
    return resolved, failures, mode


def split_pieces(sent, h, last_of_sentence, rec):
    """Split one sentence into cue-sized pieces at clause boundaries."""
    subs, orig = sent["subs"], sent["orig"]
    n = len(subs)
    if n == 0:
        return []

    full_len = len(sent["text"])
    full_dur = rec[last_of_sentence]["end"] - rec[h]["start"]
    if full_len <= MAX_CHARS and full_dur <= MAX_DUR:
        return [(0, n - 1)]

    # Candidate cut points: the start of a clause, or just after a comma.
    cands = []
    for i in range(1, n):
        head = orig[i].lower().strip(".,!?;:\u201c\u201d()")
        if head in CLAUSE_STARTERS or orig[i - 1].rstrip().endswith(","):
            cands.append(i)

    pieces, start = [], 0
    while start < n:
        piece_dur = rec[h + n - 1]["end"] - rec[h + start]["start"]
        if len(piece_text(sent, start, n - 1)) <= MAX_CHARS and piece_dur <= MAX_DUR:
            pieces.append((start, n - 1))
            break
        best = None
        for c in cands:
            if c <= start:
                continue
            txt = piece_text(sent, start, c)
            n_txt = len(txt)
            if n_txt > MAX_CHARS:
                # A clause break past the display limit is not usable. Keep an
                # earlier legal candidate, or let the width fallback below
                # choose the last fitting word boundary.
                break
            prev_i, next_i = h + c - 1, h + c
            gap = max(0.0, rec[next_i]["start"] - rec[prev_i]["end"])
            score = abs(n_txt - TARGET_CHARS) - PAUSE_WEIGHT * min(gap, 1.0)
            if best is None or score < best[0]:
                best = (score, c)
        if best is None:
            # Screen width is a real constraint. If there is no grammatical
            # boundary, fall back to the best word boundary that still fits.
            fallbacks = []
            for c in range(start + 1, n):
                if sent["sub2word"][c] == sent["sub2word"][c - 1]:
                    continue
                txt = piece_text(sent, start, c - 1)
                if len(txt) > MAX_CHARS:
                    break
                gap = max(0.0, rec[h + c]["start"] - rec[h + c - 1]["end"])
                score = abs(len(txt) - TARGET_CHARS) - PAUSE_WEIGHT * min(gap, 1.0)
                fallbacks.append((score, c))
            if not fallbacks:
                pieces.append((start, n - 1))
                break
            best = min(fallbacks)
        c = best[1]
        pieces.append((start, c - 1))
        start = c
    return pieces


def build_cues(sentences, resolved, rec):
    cues = []
    for r in resolved:
        sent = sentences[r["index"]]
        span = r["last"] - r["h"] + 1
        if span != len(sent["subs"]):
            # Anchor found a different length than expected; keep it whole.
            cues.append({"h": r["h"], "last": r["last"], "text": sent["text"],
                         "index": r["index"]})
            continue
        for a, b in split_pieces(sent, r["h"], r["last"], rec):
            cues.append({"h": r["h"] + a, "last": r["h"] + b,
                         "text": piece_text(sent, a, b), "index": r["index"]})
    return cues


def assign_times(cues, rec):
    """Give every cue a span that fully contains its words and never overlaps.

    The boundary between two cues is the midpoint between the last word of the
    first and the first word of the second; when there is room, a small lead-in
    and tail are used instead. Either way no word ends up outside its cue,
    which is what made subtitles disappear before the line finished.
    """
    cues.sort(key=lambda c: c["h"])
    for c in cues:
        c["ws"] = rec[c["h"]]["start"]
        c["we"] = rec[c["last"]]["end"]
    for c in cues:
        c["start"] = max(0.0, c["ws"] - LEAD)
        c["end"] = c["we"] + TAIL

    conflicts = []
    for i in range(len(cues) - 1):
        left, right = cues[i], cues[i + 1]
        if left["end"] <= right["start"]:
            continue
        mid = (left["we"] + right["ws"]) / 2
        if left["we"] > right["ws"]:
            conflicts.append({
                "left": i, "right": i + 1,
                "overlap": left["we"] - right["ws"],
            })
        left["end"] = mid
        right["start"] = mid

    for i, c in enumerate(cues):
        if c["end"] <= c["start"]:
            conflicts.append({"cue": i, "invalid_duration": c["end"] - c["start"]})
            c["end"] = c["start"] + 0.05
        if c["start"] > c["ws"] + 0.001 or c["end"] < c["we"] - 0.001:
            conflicts.append({
                "cue": i,
                "coverage": (c["start"] - c["ws"], c["end"] - c["we"]),
            })
    return cues, conflicts


def build_ass(cues, width, height, title):
    scale = height / 1080.0
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = str(width)
    subs.info["PlayResY"] = str(height)
    subs.info["Title"] = title
    subs.info["ScriptType"] = "v4.00+"
    subs.info["WrapStyle"] = "2"
    subs.info["ScaledBorderAndShadow"] = "yes"
    st = pysubs2.SSAStyle()
    st.fontname = "Microsoft YaHei"
    st.fontsize = round(46 * scale)
    st.primarycolor = pysubs2.Color(255, 255, 255, 0)
    st.outlinecolor = pysubs2.Color(0, 0, 0, 0)
    st.backcolor = pysubs2.Color(0, 0, 0, 128)
    st.borderstyle = 1
    st.outline = 2.2
    st.shadow = 0.8
    st.alignment = 2
    st.marginv = round(46 * scale)
    st.marginl = round(60 * scale)
    st.marginr = round(60 * scale)
    subs.styles["Default"] = st
    for c in cues:
        subs.append(pysubs2.SSAEvent(
            start=pysubs2.make_time(s=c["start"]),
            end=pysubs2.make_time(s=c["end"]),
            text=c["text"], style="Default"))
    return subs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sentences", nargs="+", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--media", help="source media; used to copy its resolution")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    ap.add_argument("--allow-unresolved", action="store_true",
                    help="write a partial draft even when some sentences are unresolved")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    sentences = load_sentences(args.sentences)
    rec = load_recognition(args.words)
    resolved, failures, alignment_mode = locate(sentences, rec)
    if failures and not args.allow_unresolved:
        for f in failures[:10]:
            print("  [未定位] " + sentences[f["index"]]["text"][:70])
        raise SystemExit(
            f"全局对齐仍有 {len(failures)} 句未解决；未写 ASS。"
            "修正文本或显式使用 --allow-unresolved 生成不完整草稿。"
        )
    cues = build_cues(sentences, resolved, rec)
    cues, timing_conflicts = assign_times(cues, rec)

    split = len(cues) - len(resolved)
    print(f"句子 {len(sentences)} 句；全局定位成功 {len(resolved)} 句；"
          f"长句拆出 {split} 条；失败 {len(failures)} 句")
    print(f"对齐模式：{alignment_mode}；词时间冲突：{len(timing_conflicts)} 项")
    if failures:
        for f in failures[:10]:
            print("  [未定位] " + sentences[f["index"]]["text"][:70])

    width, height = args.width, args.height
    if args.media:
        probed_width, probed_height, _ = T.probe(args.media)
        width = width or probed_width
        height = height or probed_height
    width = width or 1920
    height = height or 1080
    if not args.media and not (args.width and args.height):
        print("警告：未提供 --media 或完整尺寸，PlayRes 使用 1920x1080")
    subs = build_ass(cues, width, height, os.path.basename(args.out))
    subs.save(args.out, format_="ass")
    durs = sorted(c["end"] - c["start"] for c in cues)
    lens = sorted(len(c["text"]) for c in cues)
    print(f"输出 {len(cues)} 条：时长 中位 {durs[len(durs)//2]:.1f}s "
          f"最长 {durs[-1]:.1f}s | 字符 中位 {lens[len(lens)//2]} 最长 {lens[-1]}")


if __name__ == "__main__":
    main()
