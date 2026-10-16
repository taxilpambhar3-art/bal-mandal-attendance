# બાલ મંડળ હાજરી સિસ્ટમ (Bal Mandal Attendance Portal)

> **Web-based Face Scanner Attendance System**  
> Built with Bootstrap 5, FastAPI, SQLAlchemy, and WebRTC Camera capture.  
> Directly aligned with the specification in `docs-ui-mock.html` / `deepseek_html_20260910_538683.html`.

---

## 🚀 ઝડપી શરૂઆત (Quick Start)

### 1. સર્વર શરૂ કરો (Run Server)
```bash
cd /Users/taxilpambhar/bal-mandal-attendance
./run.sh
```
અથવા (Or via uvicorn directly):
```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

બ્રાઉઝરમાં ખોલો: **http://127.0.0.1:8000** (Auto-redirects to `/login`)

---

## 🔑 ડેમો લોગિન વિગતો (Demo Credentials)

| Role | Username | Password | Auto-Redirect Route | Description |
|---|---|---|---|---|
| **Super Admin** | `superadmin` | `password` (અથવા `admin123`) | `/super-admin/` | બધી Branches અને સમગ્ર સિસ્ટમનું Consolidated મોનિટરિંગ |
| **Branch Admin** | `maninagar_admin` | `password` (અથવા `branch123`) | `/branch-admin/` | મણિનગર Branch ના Bal Mandals અને સંચાલકોનું સંચાલન |
| **સંચાલક** | `hetal_shani` | `password` (અથવા `scan123`) | `/sanchalak/` | શનિવાર બાલ મંડળની Face Scan હાજરી અને રિપોર્ટ્સ |
| **સંચાલક** | `kavita_mangal` | `password` (અથવા `scan123`) | `/sanchalak/` | મંગળવાર બાલ મંડળની Face Scan હાજરી |

---

## 📋 મુખ્ય નિયમો (Core Business Rules)

1. **Web Based (App નહિ):** Mobile અને Desktop બંને Browser પર સરસ રીતે કામ કરે છે.
2. **Week 1–5 દર મહિને Reset:**
   - દર મહિને Week નંબર 1 થી શરૂ થાય છે.
   - Day 1–7 = Week 1, Day 8–14 = Week 2, Day 15–21 = Week 3, Day 22–28 = Week 4, Day 29–31 = Week 5.
3. **Face Scan = ફક્ત ૧ ફોટો:**
   - WebRTC લાઈવ કેમેરામાંથી 1-ક્લિક snapshot લેવાય છે અને તુરંત હાજરી માર્ક થાય છે.
4. **Bal Mandal શેડ્યૂલ:**
   - દરેક બાલ મંડળ અઠવાડિયામાં ફક્ત એક જ વાર ચોક્કસ દિવસે મળે છે.

---

## 🖥️ UI સ્ક્રીન્સ અને રૂટ્સ (All 16 Views)

| # | Screen Name | URL |
|---|---|---|
| 1 | Common Login | `/login` |
| 2 | Super Admin — Dashboard | `/super-admin/` (અથવા `/super-admin/dashboard`) |
| 3 | Super Admin — Branch List | `/super-admin/branches` |
| 4 | Super Admin — Add/Edit Branch | `/super-admin/branches/add` |
| 5 | Super Admin — Consolidated Reports | `/super-admin/reports` |
| 6 | Branch Admin — Dashboard | `/branch-admin/` (અથવા `/branch/dashboard`) |
| 7 | Branch Admin — Bal Mandal List | `/branch-admin/bal-mandals` |
| 8 | Branch Admin — Add/Edit Bal Mandal | `/branch-admin/bal-mandals/add` |
| 9 | Branch Admin — Reports | `/branch-admin/reports` |
| 10 | સંચાલક — Dashboard | `/sanchalak/` |
| 11 | સંચાલક — Face Scan | `/sanchalak/face-scan` |
| 12 | સંચાલક — Attendance Report | `/sanchalak/attendance-report` |
| 13 | સંચાલક — Custom Date Report | `/sanchalak/reports/custom` |
| 14 | સંચાલક — Top Attendees | `/sanchalak/child-report` |
| 15 | સંચાલક — History | `/sanchalak/history` |
| 16 | Face Scan — Result | `/sanchalak/face-scan/result` |
