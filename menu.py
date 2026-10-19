"""เมนูข้อความ (คนที่ 5) - เรียกใช้ตรรกะที่ทีมเขียนไว้แล้ว ไม่มีตรรกะใหม่ในไฟล์นี้

ข้อสำคัญ: เมธอดส่วนใหญ่คืน (bool, str) ไม่ throw exception
เมนูจึงแค่พิมพ์ข้อความที่ได้กลับมา และมี try/except กันโปรแกรมหยุดอีกชั้น
"""
from hash_ring import HashRing
from guest_room import GuestManager
from building_manager import BuildingManager
from experiments import load_statistics

MAX_PRINT = 20  # จำนวนรายการย้าย/ห้องที่พิมพ์สูงสุดต่อครั้ง (ที่เหลือสรุปเป็นจำนวน)

# ---------- ตัวช่วยรับ/แสดงผล ----------
def ask_int(prompt):
    while True:
        try:
            return int(input(prompt).strip())
        except ValueError:
            print("  กรุณากรอกเป็นจำนวนเต็ม")


def ask_str(prompt):
    return input(prompt).strip()


def show_result(res):
    """รองรับทั้ง (bool, str) และค่าที่ไม่ใช่ tuple"""
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], bool):
        ok, msg = res
        print(f"  {'สำเร็จ' if ok else 'ปฏิเสธ'}: {msg}")
    elif res is not None:
        print(f"  {res}")


def show_change(r):
    """แสดง BuildingChangeResult ตามหัวข้อ 4.4 ข้อ 3-4"""
    if not r.ok:
        print(f"  ปฏิเสธ: {r.message}")
        return
    print(f"  สำเร็จ: {r.message}")
    print(f"  แขกทั้งหมด K = {r.total_guests}")
    print(f"  จำนวนที่ย้าย = {r.moved_count}")
    if r.moved_rate is None:
        print(f"  อัตราย้าย: ไม่คำนวณ ({r.rate_note})")
    else:
        print(f"  อัตราย้าย = {r.moved_rate:.2%}")
    for m in r.moves[:MAX_PRINT]:
        print(f"    ({m.c},{m.s}) ห้อง {m.room_no}: {m.old_node} -> {m.new_node}")
    if len(r.moves) > MAX_PRINT:
        print(f"    ... และอีก {len(r.moves) - MAX_PRINT} รายการ")
    if r.rule_violations:
        print(f"  คำเตือน ละเมิดกฎ: {r.rule_violations}")


# ---------- คำสั่งเมนู ----------
def do_init(state):
    n = ask_int("จำนวนอาคารเริ่มต้น N: ")
    v = ask_int("virtual node ต่ออาคาร V: ")
    salt = ask_int("salt (0,1,2,...): ")
    channels = ask_int("จำนวนช่องทาง: ")
    per = ask_int("แขกเริ่มต้นต่อช่องทาง: ")
    if n < 1 or v < 1:
        print("  N และ V ต้องมากกว่า 0")
        return
    ring = HashRing([f"NODE{i:02d}" for i in range(1, n + 1)], v_nodes=v, salt=salt)
    guests = GuestManager(ring)
    show_result(guests.populate_initial(channels, per))
    state["ring"], state["guests"] = ring, guests
    state["buildings"] = BuildingManager(ring, guests)


def do_add_guest(st):
    show_result(st["guests"].add_guest(ask_int("c: "), ask_int("s: ")))


def do_add_range(st):
    c = ask_int("c: ")
    s0 = ask_int("s เริ่มต้น: ")
    cnt = ask_int("จำนวนแขก: ")
    show_result(st["guests"].add_guests_range(c, s0, cnt))


def do_remove_guest(st):
    show_result(st["guests"].remove_guest(ask_int("c: "), ask_int("s: ")))


def do_add_building(st):
    show_change(st["buildings"].add_building(ask_str("รหัสอาคารใหม่: ")))


def do_remove_building(st):
    show_change(st["buildings"].remove_building(ask_str("รหัสอาคารที่จะลบ: ")))


def do_find_guest(st):
    res = st["guests"].find_by_guest(ask_int("c: "), ask_int("s: "))
    if res is None:
        print("  ไม่พบแขกรหัสนี้")
    else:
        node, room = res
        print(f"  อยู่ที่อาคาร {node} ห้อง {room}")


def do_find_room(st):
    res = st["guests"].find_by_room(ask_str("รหัสอาคาร: "), ask_int("room_no: "))
    if res is None:
        print("  ไม่พบแขกในห้องนี้")
    else:
        print(f"  แขกรหัส {res}")


def do_list_rooms(st):
    rows = st["guests"].list_rooms()
    if not rows:
        print("  ยังไม่มีแขก")
        return
    for row in rows[:MAX_PRINT * 5]:
        print("  " + " | ".join(str(x) for x in row))
    if len(rows) > MAX_PRINT * 5:
        print(f"  ... แสดง {MAX_PRINT * 5} จากทั้งหมด {len(rows)} ห้อง")


def do_load(st):
    loads = st["guests"].load_per_node()
    print("  โหลดต่ออาคาร:")
    for node in sorted(loads):
        print(f"    {node}: {loads[node]}")
    stats = load_statistics(list(loads.values()))
    if isinstance(stats, dict):
        for k, v in stats.items():
            print(f"  {k} = {v:.4f}" if isinstance(v, float) else f"  {k} = {v}")
    else:
        print(f"  {stats}")


MENU = [
    ("เริ่มระบบ", do_init),
    ("เพิ่มแขกรายคน", do_add_guest),
    ("เพิ่มแขกเป็นกลุ่ม (c, s เริ่มต้น, จำนวน)", do_add_range),
    ("ลบแขก", do_remove_guest),
    ("เพิ่มอาคาร", do_add_building),
    ("ลบอาคาร", do_remove_building),
    ("ค้นด้วยรหัสแขก", do_find_guest),
    ("ค้นด้วยที่อยู่ห้อง (อาคาร, ห้อง)", do_find_room),
    ("แสดงรายการห้อง", do_list_rooms),
    ("รายงานความสมดุลโหลด", do_load),
]


def main():
    state = {}
    while True:
        print("\n=== Distributed Hilbert's Hotel ===")
        for i, (name, _) in enumerate(MENU, 1):
            print(f"{i:>2}. {name}")
        print(" 0. ออก")
        choice = ask_int("เลือก: ")
        if choice == 0:
            break
        if not 1 <= choice <= len(MENU):
            print("  ไม่มีเมนูนี้")
            continue
        if choice != 1 and "guests" not in state:
            print("  กรุณาเริ่มระบบก่อน (เมนู 1)")
            continue
        try:
            MENU[choice - 1][1](state)
        except Exception as e:  # กันโปรแกรมหยุดทุกกรณี
            print(f"  เกิดข้อผิดพลาด: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()