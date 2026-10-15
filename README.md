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
├── hash_ring.py      # Core Consistent Hashing Ring & ModuloNodeSelector
├── experiments.py    # ชุดการทดลอง A/B/C + กราฟ (Part 4)
├── test_all.py       # Unit tests ครอบคลุมกฎและกรณีขอบทั้งหมด
├── requirements.txt  # Third-party dependency (เฉพาะ experiments.py)
├── results/          # CSV ผลการทดลอง (สร้างอัตโนมัติ)
├── figures/          # กราฟ PNG (สร้างอัตโนมัติ)
├── .gitignore        # Git ignore rules
└── README.md         # เอกสารแนะนำและคู่มือการรัน
```

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

รันชุดการทดลองทั้งหมด (ใช้เวลาราว 10 วินาที):
```bash
python experiments.py
```

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
figures/graph_A_time_vs_K.png            # (ก) เวลาและหน่วยความจำ เทียบ K
figures/graph_B_move_rate_vs_N.png       # (ข) อัตราการย้าย เทียบ N ของทั้งสองวิธี
figures/graph_C_effect_of_V.png          # (ค) ผลของ V ต่อ CV และหน่วยความจำ
```

> **หมายเหตุการประกอบร่าง**: ปัจจุบัน `experiments.py` วัดที่ระดับวงแหวนโดยตรง
> เมื่อ `hotel_system.py` (คนที่ 2/3) พร้อมแล้ว ให้แก้ที่บล็อก `TODO(ประกอบร่าง)`
> ใน `run_experiment_A()` จุดเดียว ส่วนที่เหลือของสคริปต์ไม่ต้องแก้
