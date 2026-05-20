#!/usr/bin/env python3
"""
Vision benchmark — méri a kód-detektálás sebességét videóból.

Használat:
  python3.8 bench_vision.py --video kapufelvétel.mp4
  python3.8 bench_vision.py --video kapufelvétel.mp4 --no-cuda
  python3.8 bench_vision.py --video kapufelvétel.mp4 --loops 3
"""

import argparse
import logging
import sys
import time
from collections import deque

import cv2

logging.basicConfig(level=logging.DEBUG,
                    format="%(name)s [%(levelname)s] %(message)s")

# ── Argumentumok ──────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Vision sebesség benchmark")
parser.add_argument("--video",   required=True, help="Tesztvideó elérési útja")
parser.add_argument("--loops",   type=int, default=1,
                    help="Hányszor játssza le a videót (alapért.: 1)")
parser.add_argument("--no-cuda", action="store_true",
                    help="CUDA letiltása (CPU mód kényszerítése)")
args = parser.parse_args()

# ── CUDA override ─────────────────────────────────────────────────────────────
import components.vision as _vision_mod
if args.no_cuda:
    _vision_mod._CUDA_OK = False

from components.vision import VisionProcessor

# ── Videó megnyitása ──────────────────────────────────────────────────────────
cap = cv2.VideoCapture(args.video)
if not cap.isOpened():
    print(f"Hiba: nem sikerült megnyitni: {args.video}")
    sys.exit(1)

total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
video_fps    = cap.get(cv2.CAP_PROP_FPS) or 30
width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

processor = VisionProcessor()
mode = "GPU (CUDA)" if processor._cuda_ok else "CPU"

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

# ── Benchmark futtatás ────────────────────────────────────────────────────────
ROLLING = 30  # gördülő átlag ablak mérete

all_frame_ms   = []
detections     = []          # [(loop, frame_idx, code, elapsed_since_start)]
frame_idx      = 0
rolling_buf    = deque(maxlen=ROLLING)
loop_start_global = time.perf_counter()

for loop in range(1, args.loops + 1):
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    loop_frame = 0
    loop_start = time.perf_counter()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t0 = time.perf_counter()
        code = processor._process_frame(frame)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        all_frame_ms.append(elapsed_ms)
        rolling_buf.append(elapsed_ms)
        frame_idx  += 1
        loop_frame += 1

        if code:
            since_start = time.perf_counter() - loop_start
            detections.append((loop, loop_frame, code, since_start))

        # ── Élő kijelzés (minden 15. frame) ─────────────────────────────────
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

print()  # sortörés a \r után

# ── Eredmények ────────────────────────────────────────────────────────────────
total_time = time.perf_counter() - loop_start_global
n = len(all_frame_ms)
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
    print("  Detektált kódok  : \033[93m0 (nincs találat a videóban)\033[0m")

print()
print(f"  Mód: {mode}")
print("=" * 58)
print()

cap.release()
