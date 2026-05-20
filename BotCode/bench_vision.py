#!/usr/bin/env python3
"""
Vision benchmark — méri a kód-detektálás sebességét videóból.

Normál mód (egy videó, N loop):
  python3.8 bench_vision.py --video kapufelvétel.mp4
  python3.8 bench_vision.py --video kapufelvétel.mp4 --no-cuda
  python3.8 bench_vision.py --video kapufelvétel.mp4 --loops 3

Véletlenszerű mód (N futtatás, minden alkalommal más random videó):
  python3.8 bench_vision.py --video-dir ~/Videos --random-count 20
  python3.8 bench_vision.py --video-dir ~/Videos --random-count 100 --no-cuda
"""

import argparse
import logging
import os
import random
import sys
import time
from collections import defaultdict, deque

import cv2

logging.basicConfig(level=logging.WARNING,
                    format="%(name)s [%(levelname)s] %(message)s")

# ── Argumentumok ──────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Vision sebesség benchmark")

# Normál mód
parser.add_argument("--video",        help="Tesztvideó elérési útja (normál mód)")
parser.add_argument("--loops",        type=int, default=1,
                    help="Hányszor játssza le a videót (alapért.: 1)")

# Véletlenszerű mód
parser.add_argument("--video-dir",    help="Videók mappája (random mód)")
parser.add_argument("--random-count", type=int,
                    help="Hány futtatást végezzen random videókkal")

# Közös
parser.add_argument("--no-cuda",      action="store_true",
                    help="CUDA letiltása (CPU mód kényszerítése)")
args = parser.parse_args()

# ── Mód ellenőrzés ────────────────────────────────────────────────────────────
random_mode = args.random_count is not None

if random_mode and not args.video_dir:
    print("Hiba: --random-count használatához --video-dir szükséges")
    sys.exit(1)

if not random_mode and not args.video:
    print("Hiba: add meg a --video útvonalat, vagy használj --random-count + --video-dir módot")
    sys.exit(1)

# ── CUDA override ─────────────────────────────────────────────────────────────
import components.vision as _vision_mod
if args.no_cuda:
    _vision_mod._CUDA_OK = False

from components.vision import VisionProcessor

processor = VisionProcessor()
mode = "GPU (CUDA)" if processor._cuda_ok else "CPU"

# ══════════════════════════════════════════════════════════════════════════════
#  NORMÁL MÓD
# ══════════════════════════════════════════════════════════════════════════════
if not random_mode:
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"Hiba: nem sikerült megnyitni: {args.video}")
        sys.exit(1)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps    = cap.get(cv2.CAP_PROP_FPS) or 30
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print()
    print("=" * 58)
    print("  Vision Benchmark")
    print("=" * 58)
    print(f"  Videó     : {args.video}")
    print(f"  Felbontás : {width}×{height}  {video_fps:.0f} fps  {total_frames} frame")
    print(f"  Mód       : {mode}")
    print(f"  Ismétlés  : {args.loops}×")
    print("=" * 58)
    print()

    ROLLING = 30
    all_frame_ms      = []
    detections        = []
    frame_idx         = 0
    rolling_buf       = deque(maxlen=ROLLING)
    loop_start_global = time.perf_counter()

    for loop in range(1, args.loops + 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        loop_frame = 0
        loop_start = time.perf_counter()

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            t0         = time.perf_counter()
            code       = processor._process_frame(frame)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            all_frame_ms.append(elapsed_ms)
            rolling_buf.append(elapsed_ms)
            frame_idx  += 1
            loop_frame += 1

            if code:
                since_start = time.perf_counter() - loop_start
                detections.append((loop, loop_frame, code, since_start))

            if frame_idx % 15 == 0:
                avg_roll = sum(rolling_buf) / len(rolling_buf)
                live_fps = 1000.0 / avg_roll if avg_roll > 0 else 0
                det_count = len([d for d in detections if d[0] == loop])
                pct = loop_frame / total_frames * 100
                print(
                    f"\r  Loop {loop}/{args.loops}  "
                    f"[{'█' * int(pct/5):<20}] {pct:5.1f}%  "
                    f"{avg_roll:6.2f} ms/frame  "
                    f"{live_fps:6.1f} fps  "
                    f"detektált: {det_count}",
                    end="", flush=True
                )

    print()
    cap.release()

    total_time = time.perf_counter() - loop_start_global
    n       = len(all_frame_ms)
    avg_ms  = sum(all_frame_ms) / n
    min_ms  = min(all_frame_ms)
    max_ms  = max(all_frame_ms)
    sorted_ms = sorted(all_frame_ms)
    p95_ms  = sorted_ms[int(n * 0.95)]
    p99_ms  = sorted_ms[int(n * 0.99)]
    avg_fps = 1000.0 / avg_ms if avg_ms > 0 else 0

    print()
    print("=" * 58)
    print("  Eredmények")
    print("=" * 58)
    print(f"  Összes frame     : {n}")
    print(f"  Összes idő       : {total_time:.2f} s")
    print(f"  Átlag            : {avg_ms:.2f} ms/frame  →  {avg_fps:.1f} fps")
    print(f"  Minimum          : {min_ms:.2f} ms")
    print(f"  Maximum          : {max_ms:.2f} ms")
    print(f"  P95              : {p95_ms:.2f} ms")
    print(f"  P99              : {p99_ms:.2f} ms")
    print()

    if detections:
        print(f"  Detektált kódok  : {len(detections)}")
        for loop, fidx, code, t in detections:
            print(f"    Loop {loop}  frame {fidx:>5}  t={t:.2f}s  →  \033[92m{code}\033[0m")
    else:
        print("  Detektált kódok  : \033[93m0 (nincs találat)\033[0m")

    print()
    print(f"  Mód: {mode}")
    print("=" * 58)
    print()
    sys.exit(0)


# ══════════════════════════════════════════════════════════════════════════════
#  VÉLETLENSZERŰ MÓD
# ══════════════════════════════════════════════════════════════════════════════

VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov"}

videos = [
    os.path.join(args.video_dir, f)
    for f in sorted(os.listdir(args.video_dir))
    if os.path.splitext(f)[1].lower() in VIDEO_EXTS
]

if not videos:
    print(f"Hiba: nincs videófájl a megadott mappában: {args.video_dir}")
    sys.exit(1)

total_runs  = args.random_count
idx_width   = len(str(total_runs))

print()
print("=" * 62)
print("  Vision Benchmark  —  Véletlenszerű mód")
print("=" * 62)
print(f"  Videók száma  : {len(videos)} db")
print(f"  Futtatások    : {total_runs}×")
print(f"  Feldolgozás   : {mode}")
print("=" * 62)
print()

# {basename: {runs, detections, total_ms, frames, codes}}
stats = defaultdict(lambda: {
    "runs": 0, "detections": 0, "total_ms": 0.0, "frames": 0, "codes": []
})

global_start = time.perf_counter()

for run_idx in range(1, total_runs + 1):
    rand_video = random.choice(videos)
    basename   = os.path.basename(rand_video)

    pct      = (run_idx - 1) / total_runs * 100
    bar_fill = int(pct / 5)
    print(
        f"\r  [{run_idx:{idx_width}}/{total_runs}]  "
        f"[{'█' * bar_fill:<20}] {pct:5.1f}%  "
        f"{basename:<30}",
        end="", flush=True
    )

    cap = cv2.VideoCapture(rand_video)
    if not cap.isOpened():
        continue

    processor.reset()
    run_frame_ms   = []
    run_detections = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        t0         = time.perf_counter()
        code       = processor._process_frame(frame)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        run_frame_ms.append(elapsed_ms)
        if code:
            run_detections.append(code)

    cap.release()

    s = stats[basename]
    s["runs"]       += 1
    s["detections"] += len(run_detections)
    s["frames"]     += len(run_frame_ms)
    s["total_ms"]   += sum(run_frame_ms)
    s["codes"].extend(run_detections)

# Végső progress: 100%
print(
    f"\r  [{total_runs:{idx_width}}/{total_runs}]  "
    f"[{'█' * 20}] 100.0%  {'Kész':<30}",
    flush=True
)
print()

global_elapsed   = time.perf_counter() - global_start
total_detections = sum(s["detections"] for s in stats.values())
total_frames_all = sum(s["frames"]     for s in stats.values())
total_ms_all     = sum(s["total_ms"]   for s in stats.values())
overall_avg_fps  = 1000.0 / (total_ms_all / total_frames_all) if total_frames_all > 0 else 0

# Oszlopszélességek a videónevekhez igazítva
name_w = max((len(b) for b in stats), default=20)
name_w = max(name_w, 20)

sep = "  " + "─" * (name_w + 46)

print("=" * 62)
print("  Összesített eredmények")
print("=" * 62)
print(f"  Összes futtatás  : {total_runs}")
print(f"  Összes detektálás: {total_detections}")
print(f"  Összes idő       : {global_elapsed:.1f} s")
print(f"  Átlagos sebesség : {overall_avg_fps:.1f} fps")
print()
print(f"  {'Videó':<{name_w}}  {'Fut.':>5}  {'Detek.':>6}  {'Átl. fps':>8}  {'Átl. ms':>7}  Kód(ok)")
print(sep)

for basename in sorted(stats.keys()):
    s        = stats[basename]
    avg_fps_v = (1000.0 / (s["total_ms"] / s["frames"])) if s["frames"] > 0 else 0
    avg_ms_v  = s["total_ms"] / s["frames"] if s["frames"] > 0 else 0
    codes_str = ", ".join(sorted(set(s["codes"]))) if s["codes"] else "—"
    print(
        f"  {basename:<{name_w}}  {s['runs']:>5}  {s['detections']:>6}  "
        f"{avg_fps_v:>8.1f}  {avg_ms_v:>7.2f}  {codes_str}"
    )

print(sep)
overall_avg_ms = total_ms_all / total_frames_all if total_frames_all > 0 else 0
print(
    f"  {'ÖSSZESEN':<{name_w}}  {total_runs:>5}  {total_detections:>6}  "
    f"{overall_avg_fps:>8.1f}  {overall_avg_ms:>7.2f}"
)
print()
print(f"  Feldolgozás: {mode}")
print("=" * 62)
print()
