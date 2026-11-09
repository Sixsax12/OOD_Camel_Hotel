# Distributed Hilbert's Hotel (Consistent Hashing)

โครงงานรายวิชา Object Oriented Data Structure ภาคการศึกษา 1/2569  
ระบบจัดสรรห้องพักเครือโรงแรมอนันต์แบบกระจายศูนย์ ด้วยเทคนิค **Consistent Hashing** เพื่อลดการโยกย้ายห้องพักเมื่อมีการเพิ่มหรือลดอาคาร (Node)

---

## 🛠️ ความต้องการของระบบ (System Requirements)
* **Python**: Version 3.10 ขึ้นไป (ทดสอบบน `Python 3.13.14`)
* **Standard Libraries**: `bisect`, `hashlib`, `unittest` (ไม่มี Third-party dependency ในโมดูลหลัก)

---

## 📂 โครงสร้างโปรเจกต์ (Project Structure)
```text
OOD_Camel_Hotel/
├── hash_ring.py         # Part 1: Consistent Hashing Ring & ModuloNodeSelector
├── guest_room.py        # Part 2: Guest, Cantor room_no, GuestManager + ดัชนี 2 ทาง
├── building_manager.py  # Part 3: เพิ่ม/ลบอาคาร และการย้ายแขก พร้อมรายงานผล
├── common.py            # Part 4: พารามิเตอร์การทดลอง (K, N, V, salt) ที่ใช้ร่วมกัน
├── experiments.py       # Part 4: วัดผลการทดลอง A/B/C และเขียน CSV  <-- จุดเริ่มรัน
├── plots.py             # Part 4: วาดกราฟ 3 ภาพจากผลที่วัดได้
├── test_all.py          # Unit tests ครอบคลุมกฎและกรณีขอบทั้งหมด
├── requirements.txt     # Third-party dependency (เฉพาะ experiments.py)
├── results/             # CSV ผลการทดลองและข้อมูลแขก (สร้างอัตโนมัติ)
├── figures/             # กราฟ PNG (สร้างอัตโนมัติ)
├── .gitignore           # Git ignore rules
└── README.md            # เอกสารแนะนำและคู่มือการรัน
```

ลำดับการพึ่งพา: `hash_ring` → `guest_room` → `building_manager` → `experiments` → `plots`
โดย `common.py` เป็นโมดูลกลางที่ทั้ง `experiments` และ `plots` เรียกใช้
**ถ้าจะเปลี่ยนพารามิเตอร์ของการทดลอง (K, N, V, salt) ให้แก้ที่ `common.py` ที่เดียว**

---

## 🚀 วิธีการทดสอบ (Running Tests)
รัน Unit test ทั้งหมดด้วยคำสั่ง:
```bash
python -m unittest test_all.py -v
```

---

## 📌 สรุปคุณสมบัติในส่วน Part 1: Hash Ring Core
* **64-bit SHA-256**: แมปรหัสแขกและ node เป็นตำแหน่งบน ring ขนาด $0$ ถึง $2^{64}-1$ คงที่ข้ามการรัน
* **Consistent Hash Ring**:
  * รองรับ Virtual Node ($V \ge 1$) ต่อ Node เพื่อกระจายโหลด
  * รองรับ Tie-breaking เรียงตาม `(position, node_id, j)` เมื่อตำแหน่งแฮชตรงกัน
  * ค้นหาแบบ Clockwise Wrap-around ด้วย Binary Search (`bisect.bisect_left`)
* **Edge Cases & Graceful Rejection**: ป้องกันการเพิ่ม node ซ้ำ, ลบ node ที่ไม่มีอยู่, และลบ node สุดท้าย
* **Modulo Baseline (`ModuloNodeSelector`)**: ตัวเปรียบเทียบแบบ $\text{hash(guest)} \bmod N$

---

## 📊 Part 4: การทดลองและกราฟ (`experiments.py`)

ติดตั้ง dependency (เฉพาะส่วนนี้ โมดูลหลักยังไม่มี third-party):
```bash
pip install -r requirements.txt
```

รันชุดการทดลองทั้งหมด (ใช้เวลาราว 12 วินาที):
```bash
python experiments.py
```

ส่วนนี้แยกเป็น 3 ไฟล์ตามหน้าที่: `common.py` เก็บพารามิเตอร์,
`experiments.py` วัดผลและเขียน CSV, `plots.py` วาดกราฟ
(`plots.py` ไม่คำนวณสถิติใหม่ รับผลที่วัดมาแล้วไปวาดอย่างเดียว)

สคริปต์วัดผลจาก **ระบบจริงทั้งหมด** คือเรียก `HashRing` → `GuestManager` → `BuildingManager`
ไม่ได้คำนวณเองซ้ำ ตัวเลข Big-O ในรายงานจึงตรงกับโค้ดที่ส่งจริงตามหัวข้อ 8
และเนื่องจาก `GuestManager`/`BuildingManager` เรียกแค่ `get_node` / `add_node` / `remove_node` / `nodes`
จึงใช้ `ModuloNodeSelector` แทนที่ `HashRing` ได้ตรง ๆ ทำให้การทดลอง B
เทียบสองวิธีบนระบบและชุดแขกเดียวกันได้ตามหัวข้อ 7.1

| ชุด | ตัวแปรที่เปลี่ยน | ค่าคงที่ | วัดอะไร |
| --- | --- | --- | --- |
| A | `K` = 1,000 / 10,000 / 100,000 | `N`=10, `V`=32 | เวลาสร้างวงแหวน จัดแขก ค้นหา เรียงลำดับ และหน่วยความจำ |
| B | `N` = 5 / 10 / 20 | `K`=10,000, `V`=32 | จำนวนย้าย อัตราย้าย และเวลา เทียบกับ `hash mod N` |
| C | `V` = 1 / 8 / 32 | `N`=10, `K`=10,000 | ความสมดุลโหลด (CV) หน่วยความจำวงแหวน และการย้าย |

**วิธีวัดตามหัวข้อ 7.2 ของโจทย์**
* ทุกชุดทำ 3 รอบด้วย `salt` 0, 1, 2 และใช้ salt เดียวกันกับทั้งสองวิธีในรอบเดียวกัน
* จับเวลาด้วย `time.perf_counter()` แยกตามขั้นตอน ไม่รวมเวลาแสดงผลและเขียนไฟล์
* วัดการค้นหาเป็นชุด 1,000 ครั้งแล้วหารต่อครั้ง
* รายงานค่ามัธยฐานของ 3 รอบ พร้อมช่วงต่ำสุด–สูงสุด (error bar บนกราฟ)
* วัดหน่วยความจำด้วย `tracemalloc` หักจากจุดเริ่มต้นเดียวกัน ใน**รอบที่แยกจากรอบจับเวลา**
  รายงานทั้ง current และ peak เป็น MiB (เป็นหน่วยความจำที่ Python ติดตาม ไม่ใช่ของทั้งโปรเซส)

**ผลลัพธ์ที่ได้**
```text
results/experiment_{A,B,C}_rounds.csv    # ข้อมูลดิบรายรอบ พร้อมพารามิเตอร์และ salt
results/experiment_{A,B,C}_summary.csv   # ค่าสรุป median / min / max
results/experiment_B_moves.csv           # รายการย้ายรายคน (หัวข้อ 4.4 ข้อ 3)
results/sample_guests.csv                # ข้อมูลแขก (หัวข้อ 5 ข้อ 10)
figures/graph_A_time_vs_K.png            # (ก) เวลาและหน่วยความจำ เทียบ K
figures/graph_B_move_rate_vs_N.png       # (ข) อัตราการย้าย เทียบ N ของทั้งสองวิธี
figures/graph_C_effect_of_V.png          # (ค) ผลของ V ต่อ CV และหน่วยความจำ
```

`sample_guests.csv` มีคอลัมน์ `channel_id, sequence_id, node_id, room_no` ตามที่หัวข้อ 5 ข้อ 10 กำหนด
และสคริปต์ `assert` ว่าจำนวนแถวเท่ากับจำนวนแขกในระบบพอดีตามเช็กลิสต์ก่อนส่ง
ส่วน `experiment_B_moves.csv` เก็บเฉพาะ consistent hashing รอบ `salt=0`
(ของ `hash mod N` มีหลักหมื่นแถวต่อรอบและไม่ให้ข้อมูลเกินกว่าตารางสรุป)
