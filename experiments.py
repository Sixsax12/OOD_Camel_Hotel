"""Part 4 — สคริปต์การทดลอง A/B/C และกราฟ (Distributed Hilbert's Hotel)

รับผิดชอบโดยสมาชิกคนที่ 4 ครอบคลุมหัวข้อ 7 ของโจทย์

    การทดลอง A : K = 1,000 / 10,000 / 100,000   (คงที่ N=10, V=32)
    การทดลอง B : N = 5 / 10 / 20                (คงที่ K=10,000, V=32)
    การทดลอง C : V = 1 / 8 / 32                 (คงที่ N=10, K=10,000)

กติกาการวัดตามหัวข้อ 7.2 ที่สคริปต์นี้ยึดไว้
    * ทำทุกชุด 3 รอบด้วย salt 0, 1, 2 และใช้ salt เดียวกันกับทั้งสองวิธีในรอบเดียวกัน
    * จับเวลาด้วย time.perf_counter() แยกตามขั้นตอน ไม่รวมเวลาแสดงผลและเขียนไฟล์
    * วัดการค้นหาเป็นชุด 1,000 ครั้งแล้วหารต่อครั้ง
    * รายงานค่ามัธยฐานของ 3 รอบ พร้อมช่วงต่ำสุด-สูงสุด
    * วัด tracemalloc โดยหักจุดเริ่มต้นเดียวกัน รายงาน current และ peak เป็น MiB
      และทำในรอบที่แยกจากรอบจับเวลา

วิธีรัน
    py experiments.py

ผลลัพธ์
    results/*.csv   ข้อมูลดิบรายรอบ + ค่าสรุป (median/min/max)
    figures/*.png   กราฟ 3 ภาพตามที่โจทย์กำหนด
"""

from __future__ import annotations

import csv
import gc
import statistics
import time
import tracemalloc
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # บันทึกไฟล์เท่านั้น ไม่เปิดหน้าต่าง (รันซ้ำได้ทุกเครื่อง)
import matplotlib.pyplot as plt  

from hash_ring import HashRing, ModuloNodeSelector  

# ==========================================================================
# ค่าคงที่ของการทดลอง
# ==========================================================================
MIB = 1024 * 1024
SALTS: tuple[int, ...] = (0, 1, 2)
N_CHANNELS = 10
SEARCH_BATCH = 1000
NEW_NODE_ID = "NODE_NEW"

A_K_VALUES = (1_000, 10_000, 100_000)
A_N, A_V = 10, 32

B_N_VALUES = (5, 10, 20)
B_K, B_V = 10_000, 32

C_V_VALUES = (1, 8, 32)
C_N, C_K = 10, 10_000

PROJECT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_DIR / "results"
FIGURES_DIR = PROJECT_DIR / "figures"

SALT_LABEL = ";".join(str(s) for s in SALTS)


# ==========================================================================
# ชุดข้อมูลทดลอง
# ==========================================================================
def build_guest_keys(k: int, channels: int = N_CHANNELS) -> list[tuple[int, int]]:
    """สร้างรหัสแขก (c, s) จำนวน k คน จาก `channels` ช่องทาง กระจายให้ใกล้เคียงกัน
    """
    if k < 0:
        raise ValueError("จำนวนแขก (K) ต้องไม่ติดลบ")
    if channels < 1:
        raise ValueError("จำนวนช่องทางต้องมีอย่างน้อย 1")

    base, extra = divmod(k, channels) #หารแบบ//และ%
    keys: list[tuple[int, int]] = []
    for c in range(1, channels + 1):
        count = base + (1 if c <= extra else 0)
        keys.extend((c, s) for s in range(1, count + 1))
    return keys


def build_node_ids(n: int) -> list[str]:
    """รหัสอาคารคงที่ ไม่เปลี่ยนตามจำนวนอาคาร ต"""
    if n < 1:
        raise ValueError("จำนวนอาคาร (N) ต้องมีอย่างน้อย 1")
    return [f"NODE{i:02d}" for i in range(1, n + 1)]


def cantor_room_no(c: int, s: int) -> int:
    """room_no จาก Cantor pairing ตามหัวข้อ 4.2 คำนวณด้วยจำนวนเต็มตลอด
    """
    a, b = c - 1, s - 1
    return ((a + b) * (a + b + 1)) // 2 + b + 1


def pick_probes(
    keys: list[tuple[int, int]], count: int = SEARCH_BATCH
) -> list[tuple[int, int]]:
    """เลือกรหัสแขกมา `count` รายการเพื่อวัดการค้นหาเป็นชุด กระจายการสุ่มตัวอย่างให้ทั่วชุดข้อมูล ไม่ใช่เอาแต่หัวรายการ
    """
    if not keys:
        return []
    step = max(1, len(keys) // count)
    probes = keys[::step][:count]
    while len(probes) < count:  # กรณี K < count ให้วนซ้ำจนครบชุด
        probes.extend(keys[: count - len(probes)])
    return probes


# ==========================================================================
# สถิติและการนับการย้าย
# ==========================================================================
def assign_nodes(selector, guest_keys: list[tuple[int, int]]) -> dict:
    """คำนวณอาคารของแขกทุกคนจากวงแหวน/สูตรปัจจุบัน
    """
    get_node = selector.get_node
    return {key: get_node(*key) for key in guest_keys}


def count_per_node(assignment: dict, node_ids: list[str]) -> list[int]:
    """จำนวนแขกต่ออาคาร โดยนับอาคารที่มี 0 คนด้วย"""
    counter = Counter(assignment.values())
    return [counter.get(nid, 0) for nid in node_ids]


def load_statistics(counts: list[int]) -> dict:
    """max / min / mean / SD / CV ของโหลดต่ออาคาร
    SD ใช้แบบประชากร (pstdev) เพราะนับอาคารทั้งหมดในระบบ ไม่ใช่กลุ่มตัวอย่าง
    ถ้าไม่มีแขกเลย ให้รายงานสถิติพื้นฐานเป็น 0 และไม่คำนวณ CV
    """
    if not counts:
        raise ValueError("ต้องมีอาคารอย่างน้อย 1 หลัง")

    if sum(counts) == 0:
        return {"max": 0, "min": 0, "mean": 0.0, "sd": 0.0, "cv": None}

    mean = statistics.fmean(counts)
    sd = statistics.pstdev(counts)
    return {
        "max": max(counts),
        "min": min(counts),
        "mean": mean,
        "sd": sd,
        "cv": sd / mean if mean > 0 else None,
    }


def count_moves(before: dict, after: dict) -> int:
    """จำนวนรหัสแขกที่ node_id เปลี่ยน 
    นับเป็น "คน" ไม่ใช่จำนวน virtual node ที่เปลี่ยน
    """
    return sum(1 for key, node in before.items() if after[key] != node)


def list_movers(before: dict, after: dict) -> list[tuple[tuple[int, int], str, str, int]]:
    """รายการย้าย: (รหัสแขก, อาคารเดิม, อาคารใหม่, หมายเลขห้อง) 
    room_no คงเดิมเสมอเพราะคำนวณจากรหัสแขกจึงคำนวณซ้ำ
    """
    return [
        (key, before[key], after[key], cantor_room_no(*key))
        for key in before
        if after[key] != before[key]
    ]


def check_add_rule(before: dict, after: dict, new_node_id: str) -> bool:
    """เพิ่มอาคาร: คนที่ย้ายต้องย้ายเข้าอาคารใหม่เท่านั้น 
    Consistent hashing ต้องผ่าน ส่วน hash mod N จะไม่ผ่าน
    ซึ่งเป็นประเด็นที่การทดลอง B ต้องการแสดงให้เห็น
    """
    return all(after[k] == new_node_id for k in before if after[k] != before[k])


def check_remove_rule(before: dict, after: dict, removed_node_id: str) -> bool:
    """ลบอาคาร: แขกอาคารอื่นต้องไม่ย้าย และคนในอาคารที่ถูกลบต้องย้ายออกจริง"""
    for key, node in before.items():
        if node == removed_node_id:
            if after[key] == removed_node_id:
                return False
        elif after[key] != node:
            return False
    return True


def summarize_rounds(values: list) -> dict | None:
    """ยุบผล 3 รอบเป็นมัธยฐาน พร้อมช่วงต่ำสุด-สูงสุด"""
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return {
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
        "rounds": len(clean),
    }


def measure_memory(build) -> tuple[float, float]:
    """วัดหน่วยความจำของสิ่งที่ `build()` สร้างขึ้น คืน (current_mib, peak_mib)

    หักจากจุดเริ่มต้นเดียวกันทุกครั้ง และเป็นหน่วยความจำที่ Python ติดตามด้วย
    tracemalloc ไม่ใช่ของทั้งโปรเซส 
    """
    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    keep = build()  # ต้องถือ reference ไว้จนวัดเสร็จ ไม่ให้ถูกเก็บคืนก่อน
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del keep
    gc.collect()
    return (current - baseline) / MIB, (peak - baseline) / MIB


# ==========================================================================
# การเขียนไฟล์
# ==========================================================================
def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """เขียน CSV แบบ UTF-8 """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  -> {path.relative_to(PROJECT_DIR)}  ({len(rows)} แถว)")


def group_summary(
    rows: list[dict], key_field: str, key_values, metric_fields: list[str]
) -> list[dict]:
    """ยุบผลหลายรอบของแต่ละค่าตัวแปร -> {metric: {median, min, max, rounds}}"""
    summary = []
    for value in key_values:
        group = [r for r in rows if r[key_field] == value]
        entry: dict = {key_field: value}
        for field in metric_fields:
            entry[field] = summarize_rounds([r[field] for r in group])
        summary.append(entry)
    return summary


def write_summary_csv(
    path: Path,
    summary: list[dict],
    key_field: str,
    metric_fields: list[str],
    constants: dict,
) -> None:
    """เขียนค่าสรุป median/min/max แบบ long format"""
    rows = []
    for entry in summary:
        for field in metric_fields:
            stats = entry.get(field)
            if stats is None:
                continue
            rows.append(
                {
                    **constants,
                    key_field: entry[key_field],
                    "metric": field,
                    "median": stats["median"],
                    "min": stats["min"],
                    "max": stats["max"],
                    "rounds": stats["rounds"],
                }
            )
    fields = list(constants) + [key_field, "metric", "median", "min", "max", "rounds"]
    write_csv(path, rows, fields)


# ==========================================================================
# การทดลอง A: เวลาและหน่วยความจำเทียบจำนวนแขก K
# ==========================================================================
A_FIELDS = [
    "experiment", "salt", "N", "V", "K",
    "t_build_ring_s", "t_assign_guests_s", "t_sort_rooms_s",
    "t_search_ring_us", "t_search_guest_index_us", "t_search_room_index_us",
    "mem_current_mib", "mem_peak_mib",
]
A_METRICS = [f for f in A_FIELDS if f.startswith(("t_", "mem_"))]


def run_experiment_A() -> list[dict]:
    """เวลาจัดแขก ค้นหา เรียงลำดับ และหน่วยความจำ เมื่อ K เปลี่ยน (N=10, V=32)"""
    print(f"\n=== การทดลอง A : เวลา/หน่วยความจำ เทียบ K (N={A_N}, V={A_V}) ===")
    node_ids = build_node_ids(A_N)
    rows: list[dict] = []

    for k in A_K_VALUES:
        guest_keys = build_guest_keys(k)
        probes = pick_probes(guest_keys)

        for salt in SALTS:
            # ---------------- รอบจับเวลา ----------------
            gc.collect()

            t0 = time.perf_counter()
            ring = HashRing(node_ids, v_nodes=A_V, salt=salt)
            t_build_ring = time.perf_counter() - t0

            # TODO(ประกอบร่าง): เมื่อ hotel_system.py ของคนที่ 2/3 พร้อม ให้แทนบล็อกนี้ด้วย
            #     system = HotelSystem(node_ids, v_nodes=A_V, salt=salt)
            #     system.add_guests_bulk(...)   แล้วดึง placement ออกจากระบบ
            # ส่วนที่เหลือของสคริปต์ไม่ต้องแก้
            t0 = time.perf_counter()
            placement = {
                key: (ring.get_node(*key), cantor_room_no(*key)) for key in guest_keys
            }
            t_assign = time.perf_counter() - t0

            # ดัชนีค้นหา 2 ทาง(สร้างไว้ก่อน ไม่นับเวลาส่วนนี้)
            guest_index = placement
            room_index = {addr: key for key, addr in placement.items()}
            probe_rooms = [placement[key] for key in probes]

            # เรียงรายการห้อง: node_id น้อยไปมาก แล้ว room_no แบบตัวเลข
            t0 = time.perf_counter()
            sorted_rooms = sorted(placement.values())
            t_sort = time.perf_counter() - t0

            # ค้นหาเป็นชุด 1,000 ครั้งแล้วหารต่อครั้ง รายงานเป็นไมโครวินาที
            t0 = time.perf_counter()
            for c, s in probes:
                ring.get_node(c, s)  # คำนวณจากวงแหวนสด ๆ 
            t_search_ring = (time.perf_counter() - t0) / len(probes) * 1e6

            t0 = time.perf_counter()
            for key in probes:
                guest_index[key]  # รหัสแขก -> ที่อยู่ห้อง
            t_search_guest = (time.perf_counter() - t0) / len(probes) * 1e6

            t0 = time.perf_counter()
            for addr in probe_rooms:
                room_index[addr]  # (node_id, room_no) -> รหัสแขก
            t_search_room = (time.perf_counter() - t0) / len(probes) * 1e6

            assert len(sorted_rooms) == k, "จำนวนห้องที่เรียงได้ต้องเท่ากับจำนวนแขก"
            assert len(room_index) == k, "ที่อยู่ห้องต้องไม่ซ้ำกันเลย (หัวข้อ 9.2 ข้อ 2)"
            del placement, guest_index, room_index, probe_rooms, sorted_rooms, ring

            # ---------------- รอบวัดหน่วยความจำ (แยกจากรอบจับเวลา) ----------------
            def build(salt=salt, guest_keys=guest_keys):
                mem_ring = HashRing(node_ids, v_nodes=A_V, salt=salt)
                mem_placement = {
                    key: (mem_ring.get_node(*key), cantor_room_no(*key))
                    for key in guest_keys
                }
                mem_room_index = {addr: key for key, addr in mem_placement.items()}
                return mem_ring, mem_placement, mem_room_index

            mem_current, mem_peak = measure_memory(build)

            rows.append(
                {
                    "experiment": "A",
                    "salt": salt,
                    "N": A_N,
                    "V": A_V,
                    "K": k,
                    "t_build_ring_s": round(t_build_ring, 9),
                    "t_assign_guests_s": round(t_assign, 9),
                    "t_sort_rooms_s": round(t_sort, 9),
                    "t_search_ring_us": round(t_search_ring, 6),
                    "t_search_guest_index_us": round(t_search_guest, 6),
                    "t_search_room_index_us": round(t_search_room, 6),
                    "mem_current_mib": round(mem_current, 6),
                    "mem_peak_mib": round(mem_peak, 6),
                }
            )

        group = [r for r in rows if r["K"] == k]
        print(
            f"  K={k:>7,} | จัดแขก {statistics.median(r['t_assign_guests_s'] for r in group):8.4f} s"
            f" | เรียง {statistics.median(r['t_sort_rooms_s'] for r in group):7.4f} s"
            f" | ค้นวงแหวน {statistics.median(r['t_search_ring_us'] for r in group):6.3f} us/ครั้ง"
            f" | peak {statistics.median(r['mem_peak_mib'] for r in group):7.2f} MiB"
        )

    return rows


# ==========================================================================
# การทดลอง B: จำนวน/อัตราการย้ายเทียบจำนวนอาคาร N และเทียบกับ hash mod N
# ==========================================================================
B_FIELDS = [
    "experiment", "salt", "N", "V", "K", "method", "operation", "target_node",
    "moved", "move_rate", "expected_moved", "expected_rate",
    "t_ring_update_s", "t_find_movers_s", "move_rule_ok",
]
B_METHODS = ("consistent", "modulo")
B_OPERATIONS = ("add", "remove")


def _build_selector(method: str, node_ids: list[str], salt: int):
    """สร้างตัวเลือกอาคารตามวิธีที่ระบุ ใช้ salt เดียวกันทั้งสองวิธีในรอบเดียวกัน"""
    if method == "consistent":
        return HashRing(node_ids, v_nodes=B_V, salt=salt)
    return ModuloNodeSelector(node_ids, salt=salt)


def run_experiment_B() -> list[dict]:
    """เพิ่ม 1 อาคารและลบ 1 อาคาร: จำนวนย้าย อัตราย้าย และเวลา เทียบ hash mod N"""
    print(f"\n=== การทดลอง B : การย้ายเทียบ N (K={B_K:,}, V={B_V}) ===")
    guest_keys = build_guest_keys(B_K)
    rows: list[dict] = []

    for n in B_N_VALUES:
        node_ids = build_node_ids(n)
        removed_id = node_ids[0]

        for salt in SALTS:
            for method in B_METHODS:
                for operation in B_OPERATIONS:
                    # เริ่มจากสถานะ N อาคารใหม่ทุกครั้ง เพื่อให้เพิ่มและลบเทียบกันได้
                    selector = _build_selector(method, node_ids, salt)
                    before = assign_nodes(selector, guest_keys)

                    target = NEW_NODE_ID if operation == "add" else removed_id

                    # (ก) ปรับวงแหวน -- แยกเวลา
                    t0 = time.perf_counter()
                    if operation == "add":
                        ok, message = selector.add_node(target)
                    else:
                        ok, message = selector.remove_node(target)
                    t_ring_update = time.perf_counter() - t0
                    if not ok:
                        raise RuntimeError(f"คำสั่งถูกปฏิเสธโดยไม่คาดคิด: {message}")

                    # (ข) หาแขกที่ได้รับผลกระทบ -- แบบ ก ตรวจใหม่ทุกคน
                    t0 = time.perf_counter()
                    after = assign_nodes(selector, guest_keys)
                    t_find_movers = time.perf_counter() - t0

                    moved = count_moves(before, after)
                    if operation == "add":
                        expected_moved = B_K / (n + 1)  # ค่าคาดหวัง K/(N+1)
                        rule_ok = check_add_rule(before, after, target)
                    else:
                        expected_moved = B_K / n  # ค่าคาดหวัง K/N
                        rule_ok = check_remove_rule(before, after, target)

                    assert moved == len(
                        list_movers(before, after)
                    ), "จำนวนที่รายงานว่าย้ายต้องเท่ากับจำนวนรายการย้ายจริง"

                    rows.append(
                        {
                            "experiment": "B",
                            "salt": salt,
                            "N": n,
                            "V": B_V if method == "consistent" else 0,
                            "K": B_K,
                            "method": method,
                            "operation": operation,
                            "target_node": target,
                            "moved": moved,
                            "move_rate": round(moved / B_K, 6),
                            "expected_moved": round(expected_moved, 3),
                            "expected_rate": round(expected_moved / B_K, 6),
                            "t_ring_update_s": round(t_ring_update, 9),
                            "t_find_movers_s": round(t_find_movers, 9),
                            "move_rule_ok": rule_ok,
                        }
                    )

        for method in B_METHODS:
            for operation in B_OPERATIONS:
                group = [
                    r
                    for r in rows
                    if r["N"] == n
                    and r["method"] == method
                    and r["operation"] == operation
                ]
                rate = statistics.median(r["move_rate"] for r in group)
                expected = group[0]["expected_rate"]
                rules = {r["move_rule_ok"] for r in group}
                print(
                    f"  N={n:>2} | {method:<10} | {operation:<6}"
                    f" | อัตราย้าย {rate:7.2%} (คาดหวัง {expected:6.2%})"
                    f" | กฎการย้าย {'ผ่าน' if rules == {True} else 'ไม่ผ่าน'}"
                )

    return rows


# ==========================================================================
# การทดลอง C: ผลของจำนวน virtual node V ต่อความสมดุล หน่วยความจำ และการย้าย
# ==========================================================================
C_FIELDS = [
    "experiment", "salt", "N", "V", "K", "ring_points",
    "load_max", "load_min", "load_mean", "load_sd", "load_cv",
    "moved_on_add", "move_rate_on_add",
    "mem_ring_current_mib", "mem_ring_peak_mib",
    "mem_total_current_mib", "mem_total_peak_mib",
]
C_METRICS = [
    "load_max", "load_min", "load_mean", "load_sd", "load_cv",
    "moved_on_add", "move_rate_on_add",
    "mem_ring_current_mib", "mem_ring_peak_mib",
    "mem_total_current_mib", "mem_total_peak_mib",
]


def run_experiment_C() -> list[dict]:
    """จำนวนแขกต่ออาคาร ความสมดุล (CV) หน่วยความจำ และการย้าย เมื่อ V เปลี่ยน"""
    print(f"\n=== การทดลอง C : ผลของ V (N={C_N}, K={C_K:,}) ===")
    node_ids = build_node_ids(C_N)
    guest_keys = build_guest_keys(C_K)
    rows: list[dict] = []

    for v in C_V_VALUES:
        for salt in SALTS:
            ring = HashRing(node_ids, v_nodes=v, salt=salt)
            assignment = assign_nodes(ring, guest_keys)
            stats = load_statistics(count_per_node(assignment, node_ids))

            ok, message = ring.add_node(NEW_NODE_ID)
            if not ok:
                raise RuntimeError(f"คำสั่งถูกปฏิเสธโดยไม่คาดคิด: {message}")
            after = assign_nodes(ring, guest_keys)
            moved = count_moves(assignment, after)
            del ring, assignment, after

            # รอบวัดหน่วยความจำแยกจากรอบข้างบน แยกเป็น 2 ส่วน
            #   (1) วงแหวนอย่างเดียว -- ส่วนที่ V กระทบโดยตรง O(N x V)
            #   (2) วงแหวน + ข้อมูลแขก -- พื้นที่ข้อมูลหลัก O(NV + K)
            def build_ring_only(v=v, salt=salt):
                return HashRing(node_ids, v_nodes=v, salt=salt)

            def build_ring_and_guests(v=v, salt=salt):
                mem_ring = HashRing(node_ids, v_nodes=v, salt=salt)
                mem_assignment = assign_nodes(mem_ring, guest_keys)
                return mem_ring, mem_assignment

            mem_ring_current, mem_ring_peak = measure_memory(build_ring_only)
            mem_total_current, mem_total_peak = measure_memory(build_ring_and_guests)

            rows.append(
                {
                    "experiment": "C",
                    "salt": salt,
                    "N": C_N,
                    "V": v,
                    "K": C_K,
                    "ring_points": C_N * v,  # M = N x V
                    "load_max": stats["max"],
                    "load_min": stats["min"],
                    "load_mean": round(stats["mean"], 3),
                    "load_sd": round(stats["sd"], 3),
                    "load_cv": round(stats["cv"], 6) if stats["cv"] is not None else None,
                    "moved_on_add": moved,
                    "move_rate_on_add": round(moved / C_K, 6),
                    "mem_ring_current_mib": round(mem_ring_current, 6),
                    "mem_ring_peak_mib": round(mem_ring_peak, 6),
                    "mem_total_current_mib": round(mem_total_current, 6),
                    "mem_total_peak_mib": round(mem_total_peak, 6),
                }
            )

        group = [r for r in rows if r["V"] == v]
        print(
            f"  V={v:>2} | M={C_N * v:>4} จุด"
            f" | CV {statistics.median(r['load_cv'] for r in group):.4f}"
            f" | โหลด {statistics.median(r['load_min'] for r in group):>5.0f}"
            f"-{statistics.median(r['load_max'] for r in group):<5.0f}"
            f" | วงแหวน {statistics.median(r['mem_ring_peak_mib'] for r in group) * 1024:7.1f} KiB"
            f" | รวมข้อมูลแขก {statistics.median(r['mem_total_peak_mib'] for r in group):5.2f} MiB"
        )

    return rows


# ==========================================================================
# กราฟ (ทุกภาพต้องมีชื่อแกน หน่วย พารามิเตอร์ และความแปรปรวน 3 รอบ)
# ==========================================================================
def _errorbars(entries: list):
    """แปลงค่าสรุปเป็น (median, yerr) สำหรับ plt.errorbar โดย yerr = ช่วงต่ำสุด-สูงสุด"""
    median = [e["median"] for e in entries]
    lower = [e["median"] - e["min"] for e in entries]
    upper = [e["max"] - e["median"] for e in entries]
    return median, [lower, upper]


def _save(fig, filename: str) -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / filename
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {path.relative_to(PROJECT_DIR)}")
    return path


def plot_experiment_A(summary: list[dict]) -> Path:
    """กราฟ (ก) เวลาเทียบ K พร้อมแผงค้นหาต่อครั้งและหน่วยความจำ"""
    ks = [e["K"] for e in summary]
    fig, (ax_time, ax_search, ax_mem) = plt.subplots(1, 3, figsize=(16, 4.8))

    for field, label in (
        ("t_assign_guests_s", "Assign K guests"),
        ("t_sort_rooms_s", "Sort room list"),
        ("t_build_ring_s", "Build ring (N x V points)"),
    ):
        median, yerr = _errorbars([e[field] for e in summary])
        ax_time.errorbar(ks, median, yerr=yerr, marker="o", capsize=4, label=label)
    ax_time.set_xscale("log")
    ax_time.set_yscale("log")
    ax_time.set_xlabel("Number of guests K (log scale)")
    ax_time.set_ylabel("Time (seconds, total)")
    ax_time.set_title("Total time vs K")
    ax_time.grid(True, which="both", alpha=0.3)
    ax_time.legend(fontsize=8)

    for field, label in (
        ("t_search_ring_us", "Compute node from ring  O(log M)"),
        ("t_search_guest_index_us", "Guest id -> room (dict)"),
        ("t_search_room_index_us", "Room -> guest id (dict)"),
    ):
        median, yerr = _errorbars([e[field] for e in summary])
        ax_search.errorbar(ks, median, yerr=yerr, marker="s", capsize=4, label=label)
    ax_search.set_xscale("log")
    ax_search.set_xlabel("Number of guests K (log scale)")
    ax_search.set_ylabel("Time per lookup (microseconds)")
    ax_search.set_title(f"Search cost (batch of {SEARCH_BATCH:,} lookups)")
    ax_search.grid(True, which="both", alpha=0.3)
    ax_search.legend(fontsize=8)

    for field, label, marker in (
        ("mem_peak_mib", "peak", "o"),
        ("mem_current_mib", "current", "s"),
    ):
        median, yerr = _errorbars([e[field] for e in summary])
        ax_mem.errorbar(ks, median, yerr=yerr, marker=marker, capsize=4, label=label)
    ax_mem.set_xscale("log")
    ax_mem.set_yscale("log")  # log-log: O(K) จะปรากฏเป็นเส้นตรงความชัน 1
    ax_mem.set_xlabel("Number of guests K (log scale)")
    ax_mem.set_ylabel("Memory traced by tracemalloc (MiB, log scale)")
    ax_mem.set_title("Memory vs K (not whole-process RSS)")
    ax_mem.grid(True, which="both", alpha=0.3)
    ax_mem.legend(fontsize=8)

    fig.suptitle(
        f"Experiment A - Consistent hashing, N={A_N}, V={A_V},"
        f" guests from {N_CHANNELS} channels"
        f" | median of 3 rounds (salt {SALT_LABEL}), error bars = min-max",
        fontsize=10,
    )
    fig.tight_layout()
    return _save(fig, "graph_A_time_vs_K.png")


def plot_experiment_B(rows: list[dict]) -> Path:
    """กราฟ (ข) อัตราการย้ายเทียบ N ของทั้งสองวิธี พร้อมเส้นค่าคาดหวัง"""
    ns = list(B_N_VALUES)
    fig, (ax_rate, ax_time) = plt.subplots(1, 2, figsize=(12.5, 4.8))

    styles = {
        ("consistent", "add"): ("tab:blue", "-", "o"),
        ("consistent", "remove"): ("tab:cyan", "-", "s"),
        ("modulo", "add"): ("tab:red", "--", "^"),
        ("modulo", "remove"): ("tab:orange", "--", "v"),
    }

    for (method, operation), (color, line, marker) in styles.items():
        subset = [
            r for r in rows if r["method"] == method and r["operation"] == operation
        ]
        rate_entries = [
            summarize_rounds([r["move_rate"] for r in subset if r["N"] == n]) for n in ns
        ]
        median, yerr = _errorbars(rate_entries)
        ax_rate.errorbar(
            ns, median, yerr=yerr, color=color, linestyle=line, marker=marker,
            capsize=4, label=f"{method} / {operation} 1 node",
        )

        time_entries = [
            summarize_rounds([r["t_find_movers_s"] for r in subset if r["N"] == n])
            for n in ns
        ]
        median, yerr = _errorbars(time_entries)
        ax_time.errorbar(
            ns, median, yerr=yerr, color=color, linestyle=line, marker=marker,
            capsize=4, label=f"{method} / {operation}",
        )

    ax_rate.plot(ns, [1 / (n + 1) for n in ns], ":", color="gray", label="expected K/(N+1)")
    ax_rate.plot(ns, [1 / n for n in ns], ":", color="black", label="expected K/N")
    ax_rate.set_xticks(ns)
    ax_rate.set_ylim(0, 1.05)
    ax_rate.set_xlabel("Number of buildings N before the change")
    ax_rate.set_ylabel("Guests moved / K  (fraction)")
    ax_rate.set_title("Move rate vs N")
    ax_rate.grid(True, alpha=0.3)
    ax_rate.legend(fontsize=8)

    ax_time.set_xticks(ns)
    ax_time.set_xlabel("Number of buildings N before the change")
    ax_time.set_ylabel("Time to find movers (seconds)")
    ax_time.set_title("Cost of re-checking all K guests (method 'a')")
    ax_time.grid(True, alpha=0.3)
    ax_time.legend(fontsize=8)

    fig.suptitle(
        f"Experiment B - Consistent hashing (V={B_V}) vs hash mod N, K={B_K:,} guests"
        f" | median of 3 rounds (salt {SALT_LABEL}), error bars = min-max",
        fontsize=10,
    )
    fig.tight_layout()
    return _save(fig, "graph_B_move_rate_vs_N.png")


def plot_experiment_C(rows: list[dict]) -> Path:
    """กราฟ (ค) ผลของ V ต่อ CV และหน่วยความจำ"""
    vs = list(C_V_VALUES)
    fig, (ax_cv, ax_load) = plt.subplots(1, 2, figsize=(12.5, 4.8))

    cv_entries = [summarize_rounds([r["load_cv"] for r in rows if r["V"] == v]) for v in vs]
    median, yerr = _errorbars(cv_entries)
    ax_cv.errorbar(
        vs, median, yerr=yerr, color="tab:blue", marker="o", capsize=4,
        label="Load CV = SD / mean",
    )
    ax_cv.set_xscale("log", base=2)
    ax_cv.set_xticks(vs)
    ax_cv.set_xticklabels([str(v) for v in vs])
    ax_cv.set_xlabel("Virtual nodes per building V (log2 scale)")
    ax_cv.set_ylabel("Load CV (dimensionless, lower = balanced)", color="tab:blue")
    ax_cv.tick_params(axis="y", labelcolor="tab:blue")
    ax_cv.grid(True, which="both", alpha=0.3)

    # วัดเฉพาะวงแหวน (O(N x V)) เพราะถ้ารวมข้อมูลแขก K คนเข้าไป
    # ผลของ V จะถูกกลบจนมองไม่เห็น -- ค่ารวมดูได้ใน experiment_C_rounds.csv
    ax_mem = ax_cv.twinx()
    mem_entries = [
        summarize_rounds([r["mem_ring_peak_mib"] * 1024 for r in rows if r["V"] == v])
        for v in vs
    ]
    median, yerr = _errorbars(mem_entries)
    ax_mem.errorbar(
        vs, median, yerr=yerr, color="tab:red", marker="s", capsize=4,
        label="Ring peak memory (KiB)",
    )
    ax_mem.set_ylabel("tracemalloc peak memory of ring only (KiB)", color="tab:red")
    ax_mem.tick_params(axis="y", labelcolor="tab:red")
    ax_mem.set_ylim(bottom=0)  # เริ่มที่ 0 เพื่อไม่ให้สัดส่วนการเติบโตดูเกินจริง

    handles = ax_cv.get_legend_handles_labels()[0] + ax_mem.get_legend_handles_labels()[0]
    labels = ax_cv.get_legend_handles_labels()[1] + ax_mem.get_legend_handles_labels()[1]
    ax_cv.legend(handles, labels, fontsize=8, loc="center right")
    ax_cv.set_title("Trade-off: load balance vs memory")

    for field, label, marker in (
        ("load_max", "max guests in a building", "^"),
        ("load_mean", "mean guests per building", "o"),
        ("load_min", "min guests in a building", "v"),
    ):
        entries = [summarize_rounds([r[field] for r in rows if r["V"] == v]) for v in vs]
        median, yerr = _errorbars(entries)
        ax_load.errorbar(vs, median, yerr=yerr, marker=marker, capsize=4, label=label)
    ax_load.set_xscale("log", base=2)
    ax_load.set_xticks(vs)
    ax_load.set_xticklabels([str(v) for v in vs])
    ax_load.set_xlabel("Virtual nodes per building V (log2 scale)")
    ax_load.set_ylabel("Guests per building (count)")
    ax_load.set_title("Spread of guests per building")
    ax_load.grid(True, which="both", alpha=0.3)
    ax_load.legend(fontsize=8)

    fig.suptitle(
        f"Experiment C - Effect of V, N={C_N}, K={C_K:,} guests"
        f" | median of 3 rounds (salt {SALT_LABEL}), error bars = min-max",
        fontsize=10,
    )
    fig.tight_layout()
    return _save(fig, "graph_C_effect_of_V.png")


# ==========================================================================
# เมนโปรแกรม
# ==========================================================================
def _write_experiment_B_summary(rows: list[dict]) -> None:
    """ค่าสรุปของ B แยกตาม (N, method, operation) จึงเขียนเอง ไม่ใช้ group_summary"""
    summary_rows = []
    for n in B_N_VALUES:
        for method in B_METHODS:
            for operation in B_OPERATIONS:
                subset = [
                    r
                    for r in rows
                    if r["N"] == n
                    and r["method"] == method
                    and r["operation"] == operation
                ]
                for field in ("moved", "move_rate", "t_ring_update_s", "t_find_movers_s"):
                    stats = summarize_rounds([r[field] for r in subset])
                    summary_rows.append(
                        {
                            "experiment": "B",
                            "K": B_K,
                            "V": B_V,
                            "salts": SALT_LABEL,
                            "N": n,
                            "method": method,
                            "operation": operation,
                            "metric": field,
                            "median": stats["median"],
                            "min": stats["min"],
                            "max": stats["max"],
                            "rounds": stats["rounds"],
                            "expected_rate": subset[0]["expected_rate"],
                            "move_rule_ok": all(r["move_rule_ok"] for r in subset),
                        }
                    )
    write_csv(
        RESULTS_DIR / "experiment_B_summary.csv",
        summary_rows,
        [
            "experiment", "K", "V", "salts", "N", "method", "operation", "metric",
            "median", "min", "max", "rounds", "expected_rate", "move_rule_ok",
        ],
    )


def main() -> None:
    started = time.perf_counter()
    print("Distributed Hilbert's Hotel - Part 4: การทดลองและกราฟ")
    print(f"salt ที่ใช้: {SALT_LABEL}  |  แขกสร้างจาก {N_CHANNELS} ช่องทาง")

    rows_a = run_experiment_A()
    rows_b = run_experiment_B()
    rows_c = run_experiment_C()

    print("\n=== เขียนไฟล์ CSV ===")
    write_csv(RESULTS_DIR / "experiment_A_rounds.csv", rows_a, A_FIELDS)
    write_csv(RESULTS_DIR / "experiment_B_rounds.csv", rows_b, B_FIELDS)
    write_csv(RESULTS_DIR / "experiment_C_rounds.csv", rows_c, C_FIELDS)

    summary_a = group_summary(rows_a, "K", A_K_VALUES, A_METRICS)
    summary_c = group_summary(rows_c, "V", C_V_VALUES, C_METRICS)

    write_summary_csv(
        RESULTS_DIR / "experiment_A_summary.csv", summary_a, "K", A_METRICS,
        {"experiment": "A", "N": A_N, "V": A_V, "salts": SALT_LABEL},
    )
    _write_experiment_B_summary(rows_b)
    write_summary_csv(
        RESULTS_DIR / "experiment_C_summary.csv", summary_c, "V", C_METRICS,
        {"experiment": "C", "N": C_N, "K": C_K, "salts": SALT_LABEL},
    )

    print("\n=== วาดกราฟ ===")
    plot_experiment_A(summary_a)
    plot_experiment_B(rows_b)
    plot_experiment_C(rows_c)

    print(f"\nเสร็จสิ้น ใช้เวลารวม {time.perf_counter() - started:.1f} วินาที")


if __name__ == "__main__":
    main()
