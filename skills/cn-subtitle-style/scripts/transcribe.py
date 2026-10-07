"""Recognise speech in a video and export word-level timestamps.

Two ways to use it:

    # subtitles in one step, cut on sentence boundaries and pauses
    python transcribe.py input.mp4 -o output.ass

    # recognition only - no subtitle file, just the timestamps that
    # build_sentences.py needs
    python transcribe.py input.mp4 --dump-json words.json

Omit -o when the sentence-by-sentence rebuild will produce the subtitles, so
no throwaway .ass is left behind.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import whisper_env  # noqa: E402  (must run before ctranslate2 is imported)

whisper_env.setup()

import pysubs2  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

_LOCAL_MODEL = os.path.join(HERE, "models", "faster-whisper-large-v3")
_D_MODEL = r"D:\AI\whisper-models\faster-whisper-large-v3"
DEFAULT_MODEL = _D_MODEL if os.path.isdir(_D_MODEL) else _LOCAL_MODEL

# Subtitle rules (Netflix-style, adapted for a single line of English so a
# Chinese line can be added underneath later without overflowing the frame).
MAX_CHARS_PER_LINE = 42
MAX_LINES = 2
MIN_DURATION = 1.0
MAX_DURATION = 7.0
MAX_CPS = 20.0


def probe(path):
    """Return (width, height, duration) of the source video."""
    exe = os.environ.get("FFPROBE", "ffprobe")
    cmd = [
        exe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "json", path,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
        st = (data.get("streams") or [{}])[0]
        dur = float(data.get("format", {}).get("duration") or 0)
        return int(st.get("width") or 1920), int(st.get("height") or 1080), dur
    except Exception:
        return 1920, 1080, 0.0


def wrap(text, width=MAX_CHARS_PER_LINE, max_lines=MAX_LINES):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        candidate = f"{cur} {w}".strip()
        if len(candidate) <= width or not cur:
            cur = candidate
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        # Too long for the frame: spread the words over exactly max_lines rows,
        # balancing by character count. Re-wrapping against a fixed width can
        # still overflow, which is how a three-line cue slipped through before.
        total = sum(len(w) for w in words) + max(len(words) - 1, 0)
        target = total / max_lines
        lines, cur, cur_len = [], [], 0
        for w in words:
            add = len(w) + (1 if cur else 0)
            if cur and cur_len + add > target and len(lines) < max_lines - 1:
                lines.append(" ".join(cur))
                cur, cur_len = [w], len(w)
            else:
                cur.append(w)
                cur_len += add
        if cur:
            lines.append(" ".join(cur))
    return lines


def tidy(segments):
    """Merge fragments that are too short, split any that run too long."""
    cleaned = []
    for s in segments:
        text = re.sub(r"\s+", " ", s.text).strip()
        if not text:
            continue
        cleaned.append({
            "start": s.start,
            "end": s.end,
            "text": text,
            "words": [
                {"start": w.start, "end": w.end, "word": w.word}
                for w in (s.words or [])
                if w.start is not None and w.end is not None
            ],
        })
    merged = []
    for seg in cleaned:
        if merged and (seg["start"] - merged[-1]["end"] < 0.25):
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] = f"{merged[-1]['text']} {seg['text']}".strip()
            # Keep the word timings: dropping them here is what turned
            # continuous dialogue into one un-splittable 30 second cue.
            merged[-1]["words"] = merged[-1].get("words", []) + seg.get("words", [])
        else:
            merged.append(dict(seg))
    out = []
    for seg in merged:
        dur = seg["end"] - seg["start"]
        if dur < MIN_DURATION and out:
            # Absorb short fragments into the previous cue when there is room.
            prev = out[-1]
            if prev["end"] - prev["start"] + dur <= MAX_DURATION and len(prev["text"]) < 120:
                prev["end"] = seg["end"]
                prev["text"] = f"{prev['text']} {seg['text']}".strip()
                continue
        too_long = dur > MAX_DURATION or len(seg["text"]) > MAX_CHARS_PER_LINE * 2
        if too_long:
            # Word timings beat any proportional guess, so try them first.
            pieces = split_long(seg)
            if len(pieces) > 1:
                out.extend(pieces)
                continue
            parts = re.split(r"(?<=[.!?])\s+", seg["text"])
            if len(parts) > 1:
                total_chars = sum(len(p) for p in parts)
                cursor = seg["start"]
                for p in parts[:-1]:
                    span = dur * (len(p) / total_chars)
                    out.append({"start": cursor, "end": cursor + span,
                                "text": p.strip(), "words": []})
                    cursor += span
                out.append({"start": cursor, "end": seg["end"],
                            "text": parts[-1].strip(), "words": []})
                continue
        out.append(seg)

    # Whisper stretches a segment across the music or silence that surrounds a
    # line. When the words themselves are far shorter than the span, trust the
    # words so the cue does not sit on screen for a whole musical passage.
    for c in out:
        w = c.get("words") or []
        if not w:
            continue
        word_span = w[-1]["end"] - w[0]["start"]
        if (c["end"] - c["start"]) > max(word_span * 1.8, word_span + 2.0):
            c["start"] = w[0]["start"]
            c["end"] = min(c["end"], w[-1]["end"] + 0.5)
        # Whisper drifts badly over music, leaving a handful of words spread
        # across many seconds. Keep such a cue on screen only as long as the
        # text needs.
        dur = c["end"] - c["start"]
        if dur > 6.0 and len(c["text"]) < 20:
            c["end"] = c["start"] + max(1.5, 0.35 * len(c["text"]) + 1.0)
    return [s for s in out if s["text"]]


def join_words(ws):
    return re.sub(r"\s+", " ", " ".join(w["word"] for w in ws)).strip()


def clamp_cps(cues, max_cps=MAX_CPS, min_dur=0.4):
    """Give a too-fast line enough screen time without invading its neighbours.

    A line that reads faster than max_cps is shown for longer, but the extra
    time is borrowed from the idle gap before and after it. Extending the end
    unconditionally is what used to make cues overlap the next one.
    """
    for i, c in enumerate(cues):
        need = len(c["text"]) / max_cps
        have = c["end"] - c["start"]
        if have >= need:
            continue
        prev_end = cues[i - 1]["end"] if i > 0 else 0.0
        next_start = (cues[i + 1]["start"] if i + 1 < len(cues)
                      else c["end"] + (need - have))
        room_left = max(0.0, c["start"] - prev_end)
        room_right = max(0.0, next_start - c["end"])
        deficit = need - have
        take_left = min(room_left, deficit / 2)
        take_right = min(room_right, deficit - take_left)
        c["start"] = max(prev_end, c["start"] - take_left)
        c["end"] = min(next_start, c["end"] + take_right)
        if c["end"] - c["start"] < min_dur:
            c["end"] = c["start"] + min_dur
    return cues


def enforce_no_overlap(cues, min_dur=0.1):
    """Last line of defence: two cues must never be shown at the same time."""
    cues.sort(key=lambda c: (c["start"], c["end"]))
    for i in range(len(cues) - 1):
        a, b = cues[i], cues[i + 1]
        if a["end"] > b["start"]:
            a["end"] = max(a["start"] + min_dur, b["start"])
        if b["start"] < a["end"]:
            b["start"] = a["end"]
        if b["end"] <= b["start"]:
            b["end"] = b["start"] + min_dur
    return cues


def pack(chunk):
    return {"start": chunk[0]["start"], "end": chunk[-1]["end"],
            "text": join_words(chunk), "words": chunk}


def hard_split(seg, max_chars=MAX_CHARS_PER_LINE, max_dur=6.0, lookback=10,
               min_chars=14, min_piece=18):
    """Last resort for a stretch with no sentence punctuation at all.

    Cuts prefer the widest pause among the preceding words, and never close a
    cue on duration alone until it holds enough text to be worth reading.
    """
    words = seg["words"]
    gap_after = [max(0.0, words[i + 1]["start"] - words[i]["end"])
                 for i in range(len(words) - 1)] + [0.0]
    out, start = [], 0
    for i in range(len(words)):
        text = join_words(words[start:i + 1])
        dur = words[i]["end"] - words[start]["start"]
        if len(text) < max_chars and not (dur >= max_dur and len(text) >= min_chars):
            continue
        # lo may equal start: a long pause right after the opening word is a
        # perfectly good place to close a cue. Candidates must still carry
        # enough text to be worth reading, otherwise prefer the latest one.
        lo = max(start, i - lookback)
        cands = [j for j in range(lo, i)
                 if len(join_words(words[start:j + 1])) >= min_piece]
        if cands:
            k = max(cands, key=lambda j: (gap_after[j], j))
        else:
            k = max(lo, i - 1)
        out.append(pack(words[start:k + 1]))
        start = k + 1
    if start < len(words):
        out.append(pack(words[start:]))
    return out


def split_long(seg, max_chars=MAX_CHARS_PER_LINE, max_dur=7.0):
    """Break a long segment into subtitle-sized cues.

    Order matters: respect the speaker's sentence boundaries first, only then
    fall back to cutting on pauses, and never cut a sentence in half just
    because it ran past a duration target.
    """
    words = seg.get("words") or []
    if len(words) < 4:
        return [seg]

    # 1. Cut where a sentence actually ends.
    parts, cur = [], []
    for w in words:
        cur.append(w)
        if join_words(cur).endswith((".", "!", "?")):
            parts.append(cur)
            cur = []
    if cur:
        parts.append(cur)
    if len(parts) == 1:
        parts = [words]
    pieces = [pack(c) for c in parts]

    # 2. Rejoin neighbours that fit in one cue, so a short sentence does not
    #    sit alone while the next one overflows.
    merged = []
    for p in pieces:
        if merged:
            prev = merged[-1]
            if len(prev["text"]) + 1 + len(p["text"]) <= max_chars:
                prev["end"] = p["end"]
                prev["text"] = f"{prev['text']} {p['text']}"
                prev["words"] = prev["words"] + p["words"]
                continue
        merged.append(p)
    pieces = merged

    # 3. Anything still too long has no punctuation to lean on: cut on pauses.
    final = []
    for p in pieces:
        if len(p["text"]) <= max_chars and p["end"] - p["start"] <= max_dur:
            final.append(p)
        else:
            final.extend(hard_split(p, max_chars=max_chars, max_dur=max_dur))
    return final


def build_ass(segments, width, height, title=""):
    scale = height / 1080.0
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = str(width)
    subs.info["PlayResY"] = str(height)
    subs.info["Title"] = title or "Subtitles"
    subs.info["ScriptType"] = "v4.00+"
    subs.info["WrapStyle"] = "2"
    subs.info["ScaledBorderAndShadow"] = "yes"

    style = pysubs2.SSAStyle()
    style.fontname = "Microsoft YaHei"
    style.fontsize = round(46 * scale)
    style.primarycolor = pysubs2.Color(255, 255, 255, 0)
    style.outlinecolor = pysubs2.Color(0, 0, 0, 0)
    style.backcolor = pysubs2.Color(0, 0, 0, 128)
    style.bold = False
    style.borderstyle = 1
    style.outline = 2.2
    style.shadow = 0.8
    style.alignment = 2
    style.marginv = round(46 * scale)
    style.marginl = round(60 * scale)
    style.marginr = round(60 * scale)
    subs.styles["Default"] = style

    for seg in segments:
        text = "\\N".join(wrap(seg["text"]))
        subs.append(
            pysubs2.SSAEvent(
                start=pysubs2.make_time(s=seg["start"]),
                end=pysubs2.make_time(s=seg["end"]),
                text=text,
                style="Default",
            )
        )
    return subs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("-o", "--out", default=None,
                    help="write the .ass subtitle file here; omit to only export timestamps")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--language", default="en")
    ap.add_argument("--silence-ms", type=int, default=500,
                    help="pause length that ends a subtitle line")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--csv", action="store_true", help="also write a plain text/csv sidecar")
    ap.add_argument("--dump-json", default=None,
                    help="write raw segments with word-level timestamps to this path")
    ap.add_argument("--limit", type=float, default=0.0, help="only process the first N seconds")
    args = ap.parse_args()

    out = args.out
    if not out and not args.dump_json:
        ap.error("需要 -o 指定字幕输出，或用 --dump-json 只导出时间戳")
    width, height, duration = probe(args.media)

    print(f"source : {os.path.basename(args.media)}  {width}x{height}  {duration/60:.1f} min", flush=True)
    t0 = time.time()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print(f"model  : loaded in {time.time()-t0:.1f}s on {args.device}", flush=True)

    t0 = time.time()
    segments, info = model.transcribe(
        args.media,
        language=args.language,
        beam_size=args.beam,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=args.silence_ms, speech_pad_ms=200),
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    raw = list(segments)
    elapsed = time.time() - t0
    audio_len = min(duration, args.limit) if args.limit and duration else duration
    print(f"asr    : {len(raw)} raw segments in {elapsed:.0f}s"
          + (f" ({audio_len/elapsed:.1f}x realtime)" if audio_len else ""), flush=True)

    if args.dump_json:
        import json as _json
        payload = []
        for s in raw:
            payload.append({
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "words": [
                    {"start": w.start, "end": w.end, "word": w.word}
                    for w in (s.words or [])
                ],
            })
        with open(args.dump_json, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"raw    : {args.dump_json}", flush=True)

    if not out:
        print("mode   : 仅识别，未生成字幕文件", flush=True)
        return 0

    cues = tidy(raw)
    clamp_cps(cues)
    enforce_no_overlap(cues)
    subs = build_ass(cues, width, height, os.path.basename(args.media))
    subs.save(out, format_="ass")
    print(f"output : {out}  ({len(cues)} cues)", flush=True)

    if args.csv:
        side = os.path.splitext(out)[0] + ".csv"
        with open(side, "w", encoding="utf-8-sig") as f:
            f.write("start,end,text\n")
            for c in cues:
                f.write(f'{c["start"]:.2f},{c["end"]:.2f},"{c["text"]}"\n')
        print(f"sidecar: {side}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
