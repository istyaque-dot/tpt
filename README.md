# 🚚 Transport Accounts (Streamlit + Supabase + Google Drive)

Trip-wise booking, truck & party hisaab, diesel, cash / bank / petrol pump books, GR/POD copies on Google Drive.
Business rules: **LOGIC.md**.

## Files
| File | Kaam |
|---|---|
| `schema.sql` | Supabase mein ek baar chalana hai (tables) |
| `app.py` | App start, login, menu |
| `core/calc.py` | Saara hisaab (freight, hire, commission, balance, status) — tests ke saath |
| `core/trips.py` | Trip save + double-entry posting |
| `core/drive.py` | Google Drive upload |
| `views/*.py` | Screens: Dashboard, Trips, Payments, Documents, Reports, Masters, Settings |
| `get_drive_token.py` | Google Drive connect karne ke liye (ek baar, apne computer par) |

## Setup (step by step)

### 1. Supabase
1. supabase.com par **naya project** banao (region: Mumbai / ap-south-1).
2. **SQL Editor → New query** → `schema.sql` ka poora content paste → **Run**.
3. **Project Settings → Database → Connection string → Transaction pooler** (port 6543) copy karo, password daalo. Ye `DB_URL` hai.

### 2. GitHub
Naya repo (private) banao, ye saari files upload karo. `secrets.toml` kabhi upload mat karna.

### 3. Streamlit Cloud
1. share.streamlit.io → **New app** → repo chuno → main file `app.py`.
2. **Advanced settings → Secrets** mein `.streamlit/secrets.toml.example` ka content paste karke apni values bharo (`APP_PASSWORD`, `DB_URL`). Drive wala part baad mein bhi daal sakte ho.
3. Deploy. Login password = `APP_PASSWORD`.

### 4. Google Drive (GR/POD copies ke liye)
1. Ek alag Gmail banao (sirf transport documents ke liye) — recommended.
2. console.cloud.google.com → naya project → **APIs & Services → Library → Google Drive API → Enable**.
3. **OAuth consent screen** → External → app name daalo → apni email test user mein daalo → Save.
   Phir **Publish app → In production** kar do. *(Testing mode mein token 7 din mein expire ho jaata hai.)*
4. **Credentials → Create credentials → OAuth client ID → Desktop app** → JSON download (`client_secret.json`).
5. Apne computer par:
   ```
   pip install google-auth-oauthlib
   python get_drive_token.py client_secret.json
   ```
   Browser khulega → wahi Gmail se login → "Google hasn't verified this app" aaye toh **Advanced → Go to app** → Allow.
6. Jo `[google_drive]` lines print hon, Streamlit **Secrets** mein paste karo → app reboot.
7. App → **Settings → Test Drive connection**. Drive mein `Transport Docs` folder ban jaayega.

App sirf apne banaye folder/files dekh sakta hai (`drive.file` permission) — aapki baaki Drive safe hai.

## Purana database update karna
Naya version aane par Supabase → SQL Editor mein **poora `schema.sql` dobara chala do**. Ye safe hai: sirf naye
columns / tables / accounts jodta hai, purana data nahi chhoota.

## Pehli baar data bharna
1. **Masters**: Bank accounts, Parties, Truck Owners, Trucks, Petrol Pumps (opening balance ke saath). Cash tab mein opening cash.
2. **Settings**: commission default, freight loaded/unloaded, rules.
3. **Trips → New Booking**.

## Speed & login (professional version)
- **Login yaad rehta hai (30 din)**: login karte waqt "Remember on this phone" tick rehne do, phir Chrome → ⋮ →
  **Add to Home screen**. Icon se app bina password khulegi. Link kisi ko mat bhejna.
  Sab phones se logout karna ho → Streamlit secrets mein `APP_PASSWORD` ya `LOGIN_SECRET` badal do.
- **Tez**: ek baar padha hua data yaad rehta hai; kuch bhi Save karte hi taaza ho jaata hai (ya 5 minute mein).
  Typing aur screen badalne par database ka intezaar nahi.
- **Reports / Party / Documents**: sirf chuna hua hissa load hota hai.
- Sabse zyada speed ke liye app ko database ke paas (India) host karo — Streamlit Cloud ka server America mein hai.

## Mobile par use
- Phone ke Chrome mein app kholo → menu (⋮) → **Add to Home screen**. App ki tarah icon ban jaayega.
- **Home** par ek hi search box: truck no. ke last 4 digit, GR No., Trip No. ya party ka naam likho.
  Neeche filter: *All open, POD pending, Truck to pay, Party to receive, GR pending*.
- Har trip card par **➕ Entry** → Truck payment / Diesel / Party receipt / Upload GR-POD — popup mein, trip khole bina.
- Trip kholo toh upar **"Next:"** batata hai ki agla kaam kya hai, aur wahi section khula milta hai.
- Booking karte waqt naya truck ya party wahin **➕ New truck / ➕ New party** se jod sakte ho.
- Last use kiya Cash/Bank aur Petrol Pump yaad rehta hai. Amount ke box khaali aate hain (0 mitana nahi padta).

## Edit, GR, Truck Advance, Hisaab Check
- **Edit**: trip kholo → **✏️ Edit trip details** — wahi order jo New Trip mein hai, sab bhara hua. Badlo → Save.
- **GR aaya**: kisi bhi trip card par ➕ Entry → **🧾 GR No.**; ya Home → **🧾 Fill GR No.** — saari GR-pending trips ki list, ek saath kai GR likh kar ek Save.
- **💸 Truck Advance** tab: truck chuno → owner, driver, bank, chal rahi trips, ab tak diya advance/diesel, balance → advance bharo → Save. Neeche pura history.
- **🧾 Truck Settlement**: trip dhoondho → POD upload/tick → shortage-damage kaato, demurrage jodo → final hisaab → balance pay. WhatsApp text bhi.
- **📎 GR copy**: Edit trip ke andar aur New Trip save hone ke baad seedha upload.
- **🏢 Party: POD & Payment**: POD party ko jama (kai trips ek saath, docket, covering list), party ka shortage/demurrage, balance receive, payment follow-up.
- **💰 Cash / Bank Entry**: internal transfer, pump payment, kharcha, pump credit par kharcha, koi bhi payment/receipt, diesel, entries list + cancel.
- **📋 Message se trip**: New Trip mein party/broker ka WhatsApp message paste karo → **✨ Fill** → truck no. (poora ya last 4 digit), kahan se–kahan tak, weight, truck rate, freight, party, GR, material, advance, driver mobile khud bhar jaate hain. Jo nahi mila uski warning aati hai. Check karke Save.
- **📑 Statements**: Party, Petrol Pump, Truck Owner (date-wise khata + running balance + pending trips; pump mein truck-wise diesel aur litres) aur **Trip statement** (truck/party ka poora hisaab, har advance, diesel, payment, receipt). **PDF**, **WhatsApp** (party/owner ka mobile Masters mein ho toh seedha unki chat khulti hai) aur Excel/CSV.
- **💵 Party Receipt**: party ka bank transfer → amount + UTR → truck-wise baanto (ya ⚡ Auto-fill) → bacha hua "on account". Bank Book mein ek transfer = ek line.
- **🧮 Hisaab Check**: ek button — app saara hisaab dobara calculate karke books se milata hai (Debit = Credit, trip bill = formula, POD se pehle balance, zyada payment, cash minus, owner/party ledger = trips ka jod, ek truck do trip mein…). Har trip ke andar bhi "Hisaab check" — formula vs books.

## Roz ka kaam
- **Booking** → Trips → New Booking (truck baad mein bhi de sakte ho).
- **Truck advance / diesel / party advance** → trip kholo → "Add entry", ya Payments page.
- **Loading** → trip mein loaded weight + date → bill apne aap ban jaata hai.
- **GR No. aaye** → trip mein GR No. bharo.
- **POD aaye** → POD received tick (ya POD copy upload karo) → truck balance payment.
- **Party payment** → Payments → Party receipt → ek payment kai trips mein baant do.
- **Galat entry** → Payments → Entries list → Cancel (reason ke saath).

## POD bulk upload
1. Har POD page par GR No. likho, sab ek saath ADF scanner se scan karo.
2. AI chat se PDF ko GR-wise alag files mein banwao — naam `4521.pdf`, `4522.pdf`...
3. App → **GR / POD Documents → Bulk upload** → saari files ek saath → app GR se trip dhoondh kar Drive mein save karega.

## Tests
```
python tests/test_calc.py
```
