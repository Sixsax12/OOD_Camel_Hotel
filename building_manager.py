import time
from dataclasses import dataclass, field

from guest_room import GuestManager


@dataclass(frozen=True)
class MoveRecord:
    """รายการย้ายแขก 1 คน (หัวข้อ 4.4 ข้อ 3)"""
    c: int
    s: int
    old_node: str
    new_node: str
    room_no: int   # ไม่เปลี่ยนเมื่อย้ายอาคาร


@dataclass
class BuildingChangeResult:
    """ผลของการเพิ่ม/ลบอาคาร 1 ครั้ง"""
    ok: bool
    message: str
    action: str = ""                      # "add" หรือ "remove"
    building_id: str = ""
    n_before: int = 0                     # N ก่อนเปลี่ยน
    total_guests: int = 0                 # K ก่อนเปลี่ยน
    moved_count: int = 0                  # นับเป็นจำนวนรหัสแขก
    moved_rate: float | None = None       # ย้าย / K (None ถ้า K = 0)
    rate_note: str = ""
    expected_moved: float | None = None   # ค่าคาดหวัง K/(N+1) หรือ K/N
    moves: list[MoveRecord] = field(default_factory=list)
    rule_violations: list[str] = field(default_factory=list)  # ว่าง = ผ่านกติกา 4.4 ข้อ 2
    consistent: bool = True               # verify_consistency() หลังย้ายครบ
    t_ring_adjust: float = 0.0            # เวลาปรับวงแหวน (วินาที)
    t_find_affected: float = 0.0          # เวลาหาแขกที่ต้องย้าย
    t_update_data: float = 0.0            # เวลาย้ายแขกและปรับดัชนี


class BuildingManager:
    """เพิ่ม/ลบอาคาร แล้วย้ายแขกให้ตรงกับวงแหวนใหม่ (ใช้ HashRing + GuestManager)"""

    def __init__(self, ring, guests: GuestManager, check_rules: bool = True) -> None:
        self.ring = ring
        self.guests = guests
        self.check_rules = check_rules   # ใช้ ModuloNodeSelector ให้ตั้งเป็น False

    """####### เพิ่ม / ลบอาคาร #######"""
    def add_building(self, building_id: str) -> BuildingChangeResult:
        return self._change("add", building_id)

    def remove_building(self, building_id: str) -> BuildingChangeResult:
        return self._change("remove", building_id)

    def list_buildings(self) -> list[str]:
        return sorted(self.ring.nodes)

    def _change(self, action: str, building_id: str) -> BuildingChangeResult:
        n_before = len(self.ring.nodes)
        k = len(self.guests)

        # ปรับวงแหวน (ถ้าถูกปฏิเสธ ไม่แตะข้อมูลแขก)
        t0 = time.perf_counter()
        if action == "add":
            ok, msg = self.ring.add_node(building_id)
        else:
            ok, msg = self.ring.remove_node(building_id)
        t_ring = time.perf_counter() - t0
        if not ok:
            return BuildingChangeResult(
                ok=False, message=msg, action=action, building_id=str(building_id),
                n_before=n_before, total_guests=k, t_ring_adjust=t_ring,
            )
        nid = building_id.strip()

        # หาแขกที่ต้องย้าย (จุดเชื่อมกับคนที่ 2)
        t0 = time.perf_counter()
        misplaced = self.guests.find_misplaced()
        t_find = time.perf_counter() - t0

        moves = [
            MoveRecord(c, s, old, new, self.guests.guests[(c, s)].room_no)
            for (c, s, old, new) in misplaced
        ]
        moves.sort(key=lambda m: (m.c, m.s))
        violations = self._check_rules(action, nid, moves) if self.check_rules else []

        # ย้ายแขกทีละคน (ต้องย้ายให้ครบ ไม่งั้นดัชนีห้องค้างอาคารเก่า)
        t0 = time.perf_counter()
        for m in moves:
            self.guests.move_guest(m.c, m.s, m.new_node)
        t_update = time.perf_counter() - t0
        consistent = self.guests.verify_consistency()

        # อัตราย้าย (K = 0 -> ไม่คำนวณ)
        if k > 0:
            rate = len(moves) / k
            note = ""
            expected = k / (n_before + 1) if action == "add" else k / n_before
        else:
            rate = None
            note = "จำนวนย้ายเป็น 0 และไม่คำนวณอัตราย้าย เพราะไม่มีแขกในระบบ (K = 0)"
            expected = None

        return BuildingChangeResult(
            ok=True, message=msg, action=action, building_id=nid,
            n_before=n_before, total_guests=k,
            moved_count=len(moves), moved_rate=rate, rate_note=note, expected_moved=expected,
            moves=moves, rule_violations=violations, consistent=consistent,
            t_ring_adjust=t_ring, t_find_affected=t_find, t_update_data=t_update,
        )

    @staticmethod
    def _check_rules(action: str, nid: str, moves: list[MoveRecord]) -> list[str]:
        """กติกา 4.4 ข้อ 2: เพิ่ม -> ย้ายเข้าอาคารใหม่เท่านั้น / ลบ -> ย้ายเฉพาะแขกของอาคารที่ลบ"""
        problems: list[str] = []
        for m in moves:
            if action == "add" and m.new_node != nid:
                problems.append(f"({m.c},{m.s}) ย้ายไป {m.new_node} ไม่ใช่อาคารใหม่ {nid}")
            if action == "remove" and m.old_node != nid:
                problems.append(f"({m.c},{m.s}) ย้ายจาก {m.old_node} ไม่ใช่อาคารที่ลบ {nid}")
        return problems