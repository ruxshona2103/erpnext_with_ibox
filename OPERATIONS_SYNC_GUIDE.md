# OPERATIONS GUIDE — SYNC LOCK MANAGEMENT
**Language:** O'zbekcha / Uzbek  
**Target Audience:** Tekshiruv Jamoasi / QA Team, System Admins  
**Document Type:** Instant Reference Guide

---

## 🔴 AGAR SYNC TUGMALAR ISHLAMAYOTGAN BO'LSA?

### Sabab Aniqlash

```
SOLISHTIRISH JADVALI:

1. Mijozlarni Yuklash tugmasi:
   - Bosiladi → "Sinxronizatsiya boshlandi" xabari chiqadi ✓
   - Ammo 2-3 daqiqadan keyin sync qo'lda qoladi ❌
   
   SABAB: Boshqa biron bir sync (masalan, "Sync Now") ishlayapti
           va lock beradi.
   
   SOLISHTIRMA:
   ✓ NORMAL: sync_status = "Sindronizatsiya: Mijozlar yuklanmoqda..."
   ❌ LOCKED: sync_status = "Mijozlar: Boshqa sync ishlayapti ⏳"

2. Bitta sync 7+ soat to'xtab qoldi ❌
   
   SABAB: Crash job yoki stuck process — lock katta vaqt qo'lda
   
   SOLISHTIRMA:
   ❌ BEFORE: Lock 10 soat qo'lda → faqat IT team restart qiladi
   ✓ AFTER: Lock 2+ soat qo'lda → avtomatik tozalandi
   
3. Har xil xatolar log da:
   "CRITICAL: Mahsulotlar Mirror Sync ABORTED"
   
   SABAB: Cleanup 200 ta API data vs 800 ta ERPNext data ni solishtirdi
          → 75% orphan deb hisoblab → xavfsizlik sababli to'xtadi.
   
   SOLISHTIRMA:
   ❌ BEFORE: Partial syncs ham cleanup qilardi → orphan soni o'sardi
   ✓ AFTER: Partial syncs cleanup QILMAYDI
            Full sync cleanup QILADI (API to'liq bo'lganda)
```

---

## ✅ QO'LLANISH BOSQICHLAR

### 1️⃣ DEPLOY (IT TEAM)

```bash
# 1. Cache tozalash
cd /home/ruxshona/frappe-bench
bench --site ibox.com clear-cache

# 2. Restart
bench --site ibox.com restart

# Tekshirish
# 3. iBox Client form oching (Mycosmetics)
# 4. "Sinxronizatsiyani To'xtatish" tugmasi ko'rinib chiqdi?
```

### 2️⃣ AGAR LOCK BO'LSA

#### Variant A: Avtomatik Tozalash (Yangi! ✨)

```
Kutish! 2 soat kutgandan keyin, lock avtomatik tozalanadi.
```

#### Variant B: Manual Tozalash (Tez)

1. iBox Client form (Mycosmetics) oching
2. "Admin" gruppasidan "Sinxronizatsiyani To'xtatish" tugmasini bosing
3. Ogohlantirish chiqadi:
   "OGOHLANTIRISH: Bu sync qulflarini majburan tozalaydi..."
4. "OK" bosing
5. Status: "Qulflar muvaffaqiyatli to'xtatildi ✓"
6. Yangi sync boshlang

### 3️⃣ NORMAL OPERATION CYCLE

```
09:00 → Sync Now (to'liq, 30 min)
   ├─ Omborlar (5 min)
   ├─ Taminotchilar (8 min)
   ├─ Mijozlar (10 min) 
   ├─ Mahsulotlar (5 min)
   └─ Cleanup (2 min) ✓ Avtomatik qo'shiladi

09:35 → "Mijozlarni Yuklash" (qisman, 2 min)
   ├─ Cleanup? ❌ NO (partial sync guard)
   └─ Tez va xavfsiz ✓

10:00 → "Taminotchilarni Yuklash" (qisman, 1 min)
   ├─ Cleanup? ❌ NO
   └─ Tez va xavfsiz ✓
```

---

## 🚨 MUAMMO VA YECHIM (TROUBLESHOOTING)

### Problem 1: "Boshqa sync ishlayapti" xabari

```
SABAB: 
  - Boshqa jarayon ishga tushgan
  - Yoki crash qilgan ammo lock qo'lda

YECHIM:
  1. sync_status ni ko'ring → ko'tarilgan vaqtni aniqlang
  2. Agar 2+ soat ✓ → Avtomatik tozalandi
  3. Agar <2 soat ✓ → Yangi sync kutish, qayta urinish
  4. Agar kerak → "Sinxronizatsiyani To'xtatish" bosing (Admin tab)
```

### Problem 2: "Mirror Sync ABORTED" xabari log da

```
SABAB:
  ❌ OLD: Qisman sync (200 record) edi, ammo cleanup 800 dan 200 
         = 600 orphaned deb hisobladi → 75% threshold oshdi
  
  ✓ NEW: Cleanup gard → Qisman syncs cleanup QILMAYDI

YECHIM:
  1. Xato - hech narsa qilish kerak emas
  2. Yangi sync boshlang → log da ko'rishingiz shart emas
```

### Problem 3: "Force Clear Locks Error" xabari

```
SABAB: Redis bilan bog'lanish muammo

YECHIM:
  1. Redis health tekshiring: redis-cli PING
  2. Bench restart qiling
  3. Qayta urinib ko'ring
```

---

## 📊 MONITORING (SEZOMLASH)

### Har Kunlik Tekshiruv (Daily)

| Task | How | Frequency |
|---|---|---|
| Lock stuck? | Check `sync_status` field | 2x per day (9 AM, 5 PM) |
| Cleanup aborted? | Search Error Log for "ABORTED" | 1x per day (morning) |
| Sync completed? | Check `last_sync_datetime` | 1x per day |

### Bash Script (Ixtiyoriy)

```bash
#!/bin/bash
# sync_health_check.sh

# Check if lock is older than 1 hour
echo "Checking iBox sync locks..."

# SSH into server
bench --site ibox.com execute \
  "import frappe; print(frappe.cache().get_value('ibox_sync_lock_Mycosmetics'))"

# If True and >1 hour old → send alert
```

### Alert Thresholds (Hisob-kitob)

```
GREEN ✓
  - Sync completed successfully
  - Last sync < 1 day old
  - No ABORTED messages in Error Log

YELLOW ⚠️
  - Sync running for >15 minutes
  - Lock age > 30 minutes
  - One partial sync in queue

RED 🔴
  - Sync locked for >2 hours (but now auto-clears)
  - Multiple ABORTED messages
  - "Mirror Sync ABORTED" in Error Log
  → Manual intervention: "Sinxronizatsiyani To'xtatish"
```

---

## 🔧 ADMIN BUTTONS — ISLATMA

| Button | Group | Action | When to Use |
|---|---|---|---|
| Test Connection | (default) | Check iBox API | Monthly or after network changes |
| **Sinxronizatsiyani To'xtatish** | **Admin** | **Majburiy unlock** | **Lock 2+ hours stuck** |
| Sync Now | Actions | Full master sync | Weekly (scheduled) |
| Omborlarni Yuklash | Actions | Sync warehouses only | Daily |
| Taminotchilarni Yuklash | Actions | Sync suppliers only | Daily |
| Mijozlarni Yuklash | Actions | Sync customers only | Daily |
| Xaridlarni Yuklash | Actions | Sync purchases only | Daily |
| To'lovlarni Yuklash | Actions | Sync payments only | Daily |
| ... (10+ more) | Actions | Partial syncs | As needed |

---

## 📝 CHIRNOMALARI (CHECKLISTS)

### Weekly Checklist

```
[ ] Sync completed successfully last 7 days
[ ] No "CRITICAL" errors in Error Log
[ ] No stuck locks (>2 hours)
[ ] last_sync_datetime < 24 hours old
[ ] All 18 buttons responding normally
[ ] No orphan deletion issues reported
```

### Monthly Checklist

```
[ ] Test "Sinxronizatsiyani To'xtatish" button works
[ ] Review lock aging patterns
[ ] Check cleanup statistics (deleted records)
[ ] Verify no double-syncing or race conditions
[ ] Update this guide if new insights discovered
```

### After Major Changes

```
[ ] Deploy code → clear cache → restart
[ ] Test all 18 sync buttons
[ ] Monitor first 5 syncs (watch sync_status)
[ ] Check for lock issues in first 24 hours
[ ] Review Error Log for new exception patterns
```

---

## 📞 SUPPORT ESCALATION

```
Level 1: QA Team (Tekshiruv Jamoasi)
  - Check sync_status field
  - Run "Sinxronizatsiyani To'xtatish" if locked >30 min
  - Monitor for 24 hours
  
  → If still broken after 24h → Go to Level 2

Level 2: System Admin (Sistem Administratori)
  - Restart bench (clear-cache + restart)
  - Check Redis health (redis-cli PING)
  - Review Error Log for exceptions
  - Check database logs for deadlocks
  
  → If still broken after restart → Go to Level 3

Level 3: Senior Architect (Bosh Dizayner)
  - Code-level debugging
  - Check sync runner logs
  - Analyze lock patterns
  - May require code changes

CONTACT: IT Architecture Team
```

---

## 🌐 GLOSSARY

```
O'zbekcha                    | English                | Meaning
────────────────────────────|──────────────────────|─────────────────────
Qulflanish                   | Lock                 | Redis cache entry blocking sync
Eskirgan yozuv               | Orphaned Record      | In ERPNext but not in iBox API
Tozalash                     | Cleanup              | Delete orphaned records
Chegara                      | Threshold            | 15% max orphan ratio
Qisman sinx                  | Partial Sync         | Load subset of data
To'liq sinx                  | Full Sync            | Complete MASTER_SYNC_ORDER
Qulfning yoshi               | Lock Age             | How long lock stuck
Majburiy tozalash            | Force Clear          | Manual override unlock
Xavfsizlik mekanizmi         | Safety Guard         | Prevents mass deletion
Avtomatik tozalash           | Auto-clear           | After 2 hours
```

---

## ✨ BENEFITS OF THESE FIXES

```
BEFORE FIX:                          AFTER FIX:
═════════════════════════════════════════════════════════════════════

❌ Partial syncs trigger cleanup     ✓ Partial syncs skip cleanup
❌ Wrong orphan detection            ✓ Smart orphan detection
❌ Stuck locks for hours             ✓ Auto-clear after 2 hours
❌ No manual override button          ✓ Admin can force unlock
❌ Users confused by locked state     ✓ Clear status messages
❌ Mass deletion happened            ✓ 15% threshold + audit log
❌ CFO worried about data loss        ✓ CFO compliance checklist ✓

RESULT: Reliable, trustworthy sync system ✅
```

---

**Prepared By:** Senior Systems Architect  
**Last Updated:** March 16, 2026  
**Version:** 1.0  
**Status:** Production Ready
