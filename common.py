"""พารามิเตอร์การทดลองและ helper ที่ experiments.py กับ plots.py ใช้ร่วมกัน"""

from __future__ import annotations

import statistics
from pathlib import Path

MIB = 1024 * 1024
SALTS: tuple[int, ...] = (0, 1, 2)
N_CHANNELS = 10
SEARCH_BATCH = 1000
NEW_NODE_ID = "NODE_NEW"

# การทดลอง A: เปลี่ยนขนาดข้อมูล
A_K_VALUES = (1_000, 10_000, 100_000)
A_N, A_V = 10, 32

# การทดลอง B: เปลี่ยนจำนวนอาคาร
B_N_VALUES = (5, 10, 20)
B_K, B_V = 10_000, 32
B_METHODS = ("consistent", "modulo")
B_OPERATIONS = ("add", "remove")

# การทดลอง C: เปลี่ยนจำนวน virtual node
C_V_VALUES = (1, 8, 32)
C_N, C_K = 10, 10_000

PROJECT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_DIR / "results"
FIGURES_DIR = PROJECT_DIR / "figures"

SALT_LABEL = ";".join(str(s) for s in SALTS)


def summarize_rounds(values: list) -> dict | None:
    """ยุบผลหลายรอบเป็นมัธยฐาน พร้อมช่วงต่ำสุด-สูงสุด"""
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return {
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
        "rounds": len(clean),
    }
