""" ข้อสำคัญ: เมธอดส่วนใหญ่คืน (bool, str) ไม่ throw exception
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
            print(" Please Filled Integer")

def ask_str(prompt):
    return input(prompt).strip()


def show_result(res):
    """รองรับทั้ง (bool, str) และค่าที่ไม่ใช่ tuple"""
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], bool):
        ok, msg = res
        print(f"  {'Success ' if ok else 'Failed'}: {msg}")
    elif res is not None:
        print(f"  {res}")


def show_change(r):
    """แสดง BuildingChangeResult ตามหัวข้อ 4.4 ข้อ 3-4"""
    if not r.ok:
        print(f" Failed: {r.message}")
        return
    print(f"  Success: {r.message}")
    print(f"  Total Guests K = {r.total_guests}")
    print(f"  Moved Count = {r.moved_count}")
    if r.moved_rate is None:
        print(f"  Moved Rate: None ({r.rate_note})")
    else:
        print(f"  Moved Rate = {r.moved_rate:.2%}")
    for m in r.moves[:MAX_PRINT]:
        print(f"    ({m.c},{m.s}) No. Room {m.room_no}: {m.old_node} -> {m.new_node}")
    if len(r.moves) > MAX_PRINT:
        print(f"    ... and more {len(r.moves) - MAX_PRINT} lists ")
    if r.rule_violations:
        print(f"  Warning! Violated the rules: {r.rule_violations}")


# ---------- คำสั่งเมนู ----------
def do_init(state):
    n = ask_int("Number of defult building N: ")
    v = ask_int("Virtual node (per building) V: ")
    salt = ask_int("salt (0,1,2,...): ")
    channels = ask_int("Number of channel: ")
    per = ask_int("Defult Guest (per channel): ")
    if n < 1 or v < 1:
        print("  N and V must more than 0")
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
    s0 = ask_int("Defult s : ")
    cnt = ask_int("Number of guest : ")
    show_result(st["guests"].add_guests_range(c, s0, cnt))


def do_remove_guest(st):
    show_result(st["guests"].remove_guest(ask_int("c: "), ask_int("s: ")))


def do_add_building(st):
    show_change(st["buildings"].add_building(ask_str("New building ID: ")))


def do_remove_building(st):
    show_change(st["buildings"].remove_building(ask_str("Remove building ID: ")))


def do_find_guest(st):
    res = st["guests"].find_by_guest(ask_int("c: "), ask_int("s: "))
    if res is None:
        print(" Not found guest ID")
    else:
        node, room = res
        print(f" Found at building {node} room {room}")


def do_find_room(st):
    res = st["guests"].find_by_room(ask_str("Building ID: "), ask_int("room_no: "))
    if res is None:
        print(" Not found any guest in this room")
    else:
        print(f" Guest ID {res}")


def do_list_rooms(st):
    rows = st["guests"].list_rooms()
    if not rows:
        print(" Don't have any guest")
        return
    for row in rows[:MAX_PRINT * 5]:
        print("  " + " | ".join(str(x) for x in row))
    if len(rows) > MAX_PRINT * 5:
        print(f"  ... show {MAX_PRINT * 5} from {len(rows)} rooms ")


def do_load(st):
    loads = st["guests"].load_per_node()
    print(" Load per building:")
    for node in sorted(loads):
        print(f"    {node}: {loads[node]}")
    stats = load_statistics(list(loads.values()))
    if isinstance(stats, dict):
        for k, v in stats.items():
            print(f"  {k} = {v:.4f}" if isinstance(v, float) else f"  {k} = {v}")
    else:
        print(f"  {stats}")


MENU = [
    ("Run System", do_init),
    ("Add Guest (per person)", do_add_guest),
    ("Add Group (c, defult s, number of guest)", do_add_range),
    ("Remove Guest", do_remove_guest),
    ("Add Building", do_add_building),
    ("Remove Building", do_remove_building),
    ("Find Guest by ID", do_find_guest),
    ("Find Room by ID (building , room)", do_find_room),
    ("Room Lists", do_list_rooms),
    ("Load Reports", do_load),
]


def main():
    state = {}
    while True:
        print("\n=== Distributed Hilbert's Hotel ===")
        for i, (name, _) in enumerate(MENU, 1):
            print(f"{i:>2}. {name}")
        print(" 0. Exit")
        choice = ask_int("Select Number: ")
        if choice == 0:
            break
        if not 1 <= choice <= len(MENU):
            print(" Don't have this menu")
            continue
        if choice != 1 and "guests" not in state:
            print(" Please run system first (Select 1)")
            continue
        try:
            MENU[choice - 1][1](state)
        except Exception as e:  # กันโปรแกรมหยุดทุกกรณี
            print(f" Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()