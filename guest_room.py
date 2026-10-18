from dataclasses import dataclass

from hash_ring import HashRing


def cantor_room_no(c: int, s: int) -> int:
    """Cantor pairing: a=c-1, b=s-1, room = (a+b)(a+b+1)//2 + b + 1 ไม่ขึ้นกับอาคาร ไม่เปลี่ยนเมื่อแขกย้ายอาคาร"""
    _validate_guest_id(c, s)
    a, b = c - 1, s - 1
    return ((a + b) * (a + b + 1)) // 2 + b + 1


def _validate_guest_id(c: int, s: int) -> None:
    for v in (c, s):
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ValueError("รหัสช่องทาง (c) และลำดับ (s) ต้องเป็นจำนวนเต็มบวก")


@dataclass
class Guest:
    c: int
    s: int
    room_no: int   # คงที่ตลอด ไม่เปลี่ยนเมื่อย้ายอาคาร
    node_id: str   # อาคารปัจจุบัน (เปลี่ยนได้เมื่อมีการย้าย)


class GuestManager:
    """เก็บข้อมูลแขก + ดัชนี 2 ทาง และ call HashRing เพื่อหาอาคาร

    - guests:     (c, s)             -> Guest          (รหัส -> ห้อง)
    - room_index: (node_id, room_no) -> (c, s)         (ห้อง -> รหัส)
    
    สองโครงสร้างนี้จะต้องอัปเดตคู่กันเสมอ
    """

    def __init__(self, ring: HashRing) -> None:
        self.ring = ring
        self.guests: dict[tuple[int, int], Guest] = {}
        self.room_index: dict[tuple[str, int], tuple[int, int]] = {}


    """####### เพิ่ม / ลบแขก #######"""
    def _insert(self, c: int, s: int) -> Guest:
        node_id = self.ring.get_node(c, s)
        g = Guest(c, s, cantor_room_no(c, s), node_id)
        self.guests[(c, s)] = g
        self.room_index[(node_id, g.room_no)] = (c, s)
        return g

    def add_guest(self, c: int, s: int) -> tuple[bool, str]:
        try:
            _validate_guest_id(c, s)
        except ValueError as err:
            return False, str(err)
        if (c, s) in self.guests:
            return False, f"ปฏิเสธคำสั่ง: แขกรหัส ({c},{s}) มีอยู่ในระบบแล้ว"
        g = self._insert(c, s)
        return True, f"เพิ่มแขก ({c},{s}) -> อาคาร {g.node_id} ห้อง {g.room_no}"

    def add_guests(self, ids: list[tuple[int, int]]) -> tuple[bool, str]:
        """เพิ่มguestเป็นกลุ่ม: ถ้ามีรหัสซ้ำหรือไม่ถูกต้องแม้ 1 รายการ ปฏิเสธทั้งกลุ่ม (ไม่เพิ่มเลยสักคน)"""
        seen: set[tuple[int, int]] = set()
        for item in ids:
            try:
                c, s = item
                _validate_guest_id(c, s)
            except (ValueError, TypeError):
                return False, f"ปฏิเสธทั้งกลุ่ม: รหัสแขกไม่ถูกต้อง {item}"
            if (c, s) in self.guests:
                return False, f"ปฏิเสธทั้งกลุ่ม: แขก ({c},{s}) มีอยู่ในระบบแล้ว"
            if (c, s) in seen:
                return False, f"ปฏิเสธทั้งกลุ่ม: พบรหัส ({c},{s}) ซ้ำภายในกลุ่ม"
            seen.add((c, s))
        for c, s in ids:
            self._insert(c, s)
        return True, f"เพิ่มแขกเป็นกลุ่มสำเร็จ {len(ids)} คน"

    def add_guests_range(self, c: int, s_start: int, count: int) -> tuple[bool, str]:
        """เพิ่มแขกเป็นกลุ่มแบบระบุช่วง 

        รับช่องทาง c, ลำดับเริ่มต้น s_start และจำนวนแขก count
        count ต้องเป็นจำนวนเต็มไม่ติดลบ โดย 0 หมายถึงไม่เปลี่ยนข้อมูล
        ถ้าช่วงรหัสทับกับแขกที่มีอยู่ ให้ปฏิเสธทั้งกลุ่มและคงข้อมูลเดิมไว้
        (ส่งต่อให้ add_guests ซึ่งทำกติกา all-or-nothing อยู่แล้ว)
        """
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return False, "ปฏิเสธคำสั่ง: จำนวนแขกต้องเป็นจำนวนเต็มไม่ติดลบ"
        try:
            _validate_guest_id(c, s_start)
        except ValueError as err:
            return False, str(err)
        if count == 0:
            return True, "จำนวนแขกเป็น 0 จึงไม่เปลี่ยนแปลงข้อมูล"

        ids = [(c, s_start + i) for i in range(count)]
        return self.add_guests(ids)

    def populate_initial(self, channels: int, per_channel: int) -> tuple[bool, str]:
        """สร้างแขกเริ่มต้นของระบบ"""
        ids = [(c, s) for c in range(1, channels + 1) for s in range(1, per_channel + 1)]
        return self.add_guests(ids)

    def remove_guest(self, c: int, s: int) -> tuple[bool, str]:
        g = self.guests.get((c, s))
        if g is None:
            return False, f"ปฏิเสธคำสั่ง: ไม่พบแขก ({c},{s})"
        del self.guests[(c, s)]
        del self.room_index[(g.node_id, g.room_no)]
        return True, f"ลบแขก ({c},{s}) สำเร็จ"


    """######### ค้นหา 2 ทาง ##########"""
    def find_by_guest(self, c: int, s: int) -> tuple[str, int] | None:
        """รหัสแขก -> (node_id, room_no); อาคารคำนวณจากวงแหวนสดเสมอ"""
        g = self.guests.get((c, s))
        if g is None:
            return None
        return self.ring.get_node(c, s), g.room_no

    def find_by_room(self, node_id: str, room_no: int) -> tuple[int, int] | None:
        """(node_id, room_no) -> (c, s)"""
        return self.room_index.get((node_id, room_no))


    """########### แสดงผล / สถิติ #############"""
    def list_rooms(self) -> list[tuple[str, int, int, int]]:
        """[(node_id, room_no, c, s)] เรียงตาม node_id แล้ว room_no"""
        return sorted((g.node_id, g.room_no, g.c, g.s) for g in self.guests.values())

    def load_per_node(self) -> dict[str, int]:
        """จำนวนแขกต่ออาคาร (อาคารที่ไม่มีแขกได้ 0) ใช้กับรายงานความสมดุลโหลด"""
        counts = {nid: 0 for nid in self.ring.nodes}
        for g in self.guests.values():
            counts[g.node_id] = counts.get(g.node_id, 0) + 1
        return counts

    def __len__(self) -> int:
        return len(self.guests)


    """____ จุดเชื่อมกับของฟิว _____"""
    def find_misplaced(self) -> list[tuple[int, int, str, str]]:
        """แขกที่ node_id ที่เก็บไว้ไม่ตรงกับวงแหวนปัจจุบัน -> [(c, s, old, new)]
        (ใช้หลัง ring.add_node/remove_node; ไม่แก้ข้อมูล)"""
        out = []
        for (c, s), g in self.guests.items():
            new = self.ring.get_node(c, s)
            if new != g.node_id:
                out.append((c, s, g.node_id, new))
        return out

    def move_guest(self, c: int, s: int, new_node: str) -> bool:
        """ย้ายแขก: เปลี่ยนเฉพาะ node_id และดัชนี room_no คงเดิม"""
        g = self.guests.get((c, s))
        if g is None:
            return False
        del self.room_index[(g.node_id, g.room_no)]
        g.node_id = new_node
        self.room_index[(new_node, g.room_no)] = (c, s)
        return True

    def verify_consistency(self) -> bool:
        """ตรวจว่า 2 ดัชนีตรงกัน และ node_id ตรงกับวงแหวนปัจจุบัน"""
        if len(self.guests) != len(self.room_index):
            return False
        for (c, s), g in self.guests.items():
            if self.room_index.get((g.node_id, g.room_no)) != (c, s):
                return False
            if self.ring.get_node(c, s) != g.node_id:
                return False
        return True