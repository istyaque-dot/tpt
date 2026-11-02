# Transport Accounting — Business Logic (Draft v1)

Stack: Streamlit + Supabase (petrol pump v2 jaisa)
Status: v1 app bana diya (Nov 2026). Neeche 'Decisions' dekhein.

---

## 1. Masters (ek baar bharne wala data)
| Master | Fields |
|---|---|
| Party | Name, mobile, address, GSTIN, opening balance |
| Truck Owner | Name, mobile, PAN, bank details, opening balance |
| Truck | Truck No. (unique), owner (link), driver name/mobile |
| Petrol Pump | Pump name, location, opening balance |
| Bank Account | Bank name, A/c no., opening balance |
| Route / Material | From, To, Material (dropdown ke liye) |

Cash account system mein default rahega.

---

## 2. Trip (Trip No. = trip ki pehchaan)
- **Trip No.** booking ke time auto-generate hoga (jaise T-0001), **unique**, kabhi repeat nahi.
- **GR No.** kai din baad milta hai → booking ke time khali rahega, baad mein manually bhara jaayega.
- GR No. bharne par **unique check** hoga (same GR do trip mein nahi).
- Trip ko Trip No., Truck No. ya GR No. — teeno se search kar sakte hain.
- Ek trip = ek party + ek truck.

### Trip Status (isi order mein aage badhega)
1. **Booked** — party, from–to, material, party rate (₹/ton), approx weight
2. **Truck Assigned** — truck no., truck rate (₹/ton)
3. **Loaded** — loaded weight (ton), loading date
4. **Unloaded / POD** — unloaded weight, unloading date, POD received (Yes/No)
5. **Truck Settled** — truck ka balance chuka diya
6. **Party Settled** — party se balance aa gaya
7. **Closed** — dono settle hone par auto

Cancel: sirf "Truck Assigned" tak, jab tak koi payment entry na ho.

### Trip Documents (GR / POD copy)
- Har trip ke saath **GR copy** aur **POD copy** upload kar sakte hain — **kabhi bhi**, kisi bhi status mein (Closed trip mein bhi).
- Ek trip mein multiple files allowed (photo JPG/PNG ya PDF), har file ka type: GR / POD / Other.
- Mobile camera se seedha photo khinch kar upload ho sakega.
- Photo upload se pehle auto-compress hogi (storage bachane ke liye).
- **Files Google Drive mein rahengi** (Supabase mein sirf file ka link + details).
  - Folder structure: `Transport Docs / 2026 / 11-Nov / T-0001 /`
  - Drive aapke apne Google account ka hoga (OAuth login), app sirf apne folder mein likhega.
- Trip page par preview + download (Drive link se).

### Bulk Scan (POD)
- **POD ke har page par haath se GR No. likha jaayega** — har page par ek hi jagah (upar right kone mein, box mein, bade saaf ankon mein).
- Saare POD duplex ADF scanner se ek saath scan → PDF (50–100 page ke batch).
- Phase 1 (abhi): AI chat se GR-wise alag PDF banwa kar Drive mein save. AI ek list bhi dega (GR → pages) check ke liye.
- Phase 2 (baad mein): yahi kaam app ke andar — PDF upload → GR-wise kaat kar trip ke Drive folder mein khud save, doubt wale pages "Check karein" list mein.
- Upload ki date aur kisne upload kiya, save hoga.
- Galat file delete kar sakte hain (reason ke saath).

---

## 3. Freight Calculation (Per Ton)
- **Party Freight** = Loaded Weight × Party Rate
- **Truck Hire (Lorry Hire)** = Loaded Weight × Truck Rate
- **Gross Margin** = Party Freight − Truck Hire

---

## 4. Shortage
- Shortage Weight = Loaded Weight − Unloaded Weight (0 se kam nahi)
- **Party shortage deduction** = party jitna kaatati hai (amount entry)
- **Truck shortage deduction** = hum truck se jitna kaatte hain (amount entry)
- Dono alag-alag rakhe jaayenge — zaroori nahi ke barabar ho.

---

## 5. Truck Side Hisaab
Truck Balance =
  Truck Hire
  − Cash/Bank Advance
  − Diesel (pump se, hamare khate par)
  − Commission
  − Truck Shortage Deduction

- Advance multiple baar de sakte hain (cash ya bank).
- **Diesel**: driver pump se diesel leta hai → Pump ka udhaar badhta hai, truck ka advance maana jaata hai.
- Balance payment **POD aane ke baad hi** allowed.
- Balance kabhi negative ho jaye toh warning (truck owner se wapas lena hai).

## 6. Party Side Hisaab
Party Balance =
  Party Freight
  − Advance Received (cash/bank, multiple)
  − Party Shortage Deduction

---

## 7. Accounts / Ledgers (har entry double-entry)
| Event | Debit | Credit |
|---|---|---|
| Trip loaded (party bill) | Party | Freight Income |
| Trip loaded (truck hire) | Lorry Hire Expense | Truck Owner |
| Party advance/balance aaya | Cash / Bank | Party |
| Truck advance/balance diya | Truck Owner | Cash / Bank |
| Diesel liya pump se | Truck Owner | Petrol Pump |
| Pump ko payment | Petrol Pump | Cash / Bank |
| Commission kaata | Truck Owner | Commission Income |
| Party shortage kaati | Shortage Expense | Party |
| Truck se shortage kaati | Truck Owner | Shortage Recovery |
| Cash bank mein jama | Bank | Cash |

Har payment entry mein Trip No. link hoga (pump payment aur contra ko chhodkar). Ledger/report mein GR No. bhi dikhega jab bhar diya gaya ho.

---

## 8. Reports
- Trip Register (date-wise, status-wise, Trip / GR / truck no. se search)
- **Pending GR list** (jin trips ka GR No. abhi nahi aaya)
- **Missing documents list** (jin trips ki GR/POD copy upload nahi hui)
- Party Ledger & outstanding list
- Truck Owner Ledger & payable list
- Petrol Pump Ledger (diesel trip-wise)
- Cash Book, Bank Book (daily opening/closing)
- Trip-wise Profit (margin + commission + shortage difference)
- Pending POD list

---

## 9. Locking Rules
- Truck settle hone ke baad truck side ki entries lock (sirf edit/cancel button se, reason ke saath).
- Party settle hone ke baad party side lock.
- Closed trip edit nahi hogi.

---

## ✅ Decisions in v1 (Settings page se badal sakte hain)
1. **Commission**: har trip mein Fixed ₹ ya Truck Hire ka % — dono option. Default Settings mein.
2. **Weight**: Loaded ya Unloaded — Settings mein default; har trip mein apna basis save hota hai, isliye setting badalne se purani trips nahi badalti. Unloaded basis mein unloaded weight aane tak loaded weight lagta hai.
3. **Party bill**: abhi sirf hisaab, GST invoice nahi (baad mein).
4. **Diesel**: amount zaroori; litres × rate optional (amount 0 chhodo toh litres × rate se ban jaata hai).
5. **Users**: abhi ek login (password). Staff roles baad mein.
6. **GR print**: nahi.
7. **GR ke bina truck balance**: by default allowed; Settings mein "GR zaroori" on kar sakte hain.
8. **POD upload**: by default POD copy upload hote hi trip "POD received" ho jaati hai (Settings mein band kar sakte hain).

## Trip entry ka order (mobile screen)
Truck No. → Destination → Weight → Truck rate → Freight rate → Freight paying company → GR No. (agar ho) → Comment.
- Weight bhar diya toh trip usi din **Loaded** maani jaati hai (loading date = trip date) aur bill ban jaata hai.
- Truck hire, party freight aur margin likhte waqt hi screen par dikhte hain.
- From (kahan se) optional hai; pichhli baar wala yaad rehta hai.
- Comment har trip card par dikhta hai.

## Truck Settlement (balance payment)
Trip dhoondho (truck ke last digits / GR / Trip No.) → POD → kat-kaat → final hisaab → balance.
- **POD**: copy upload karo (camera/gallery) ya "POD original received" tick. POD ke bina balance nahi.
- **Shortage / damage cut from truck ₹** → truck ke balance se katega (Truck Owner Dr / Shortage Recovery Cr).
- **Demurrage to truck ₹** (+ days) → truck ko extra milega (Demurrage Paid Dr / Truck Owner Cr).
- **Demurrage charged to party ₹** (optional) → party ke bill mein judega (Party Dr / Demurrage Charged Cr).
- **Shortage cut by party ₹** → party balance se kam.
- Truck Balance = Hire + Demurrage − Advance − Diesel − Commission − Shortage/Damage
- Party Balance = Freight + Party Demurrage − Received − Party Shortage
- Profit = Margin + Commission − Party Shortage + Truck Shortage + Party Demurrage − Truck Demurrage
- Badlaav likhte hi final hisaab screen par badalta hai; "Save & pay balance" dono ek saath save karta hai.
- WhatsApp ke liye settlement text copy kar sakte ho.

## Party side: POD jama + settlement
- **POD jama karo (bulk)**: party chuno → jin trips ki POD truck se aa gayi par party ko nahi di, unki list → tick → date, kaise (hand/courier/email/WhatsApp), docket no. → Save. Covering list copy/CSV milti hai.
- **Party settlement (ek trip)**: POD given status, **shortage/damage cut by party ₹**, **demurrage charged to party ₹** (+ days) → final hisaab (Freight + Demurrage − Received − Shortage) → balance receive (bank).
- **Follow-up**: POD de di, payment baaki — party-wise, sabse purani pehle, kitne din ho gaye.
- Accounting: Party Dr / Demurrage Charged Cr; Shortage Expense Dr / Party Cr; receipt Bank Dr / Party Cr.

## Cash / Bank Entry (baaki saare paise ke kaam)
| Type | Debit | Credit |
|---|---|---|
| Internal transfer (bank↔bank, cash↔bank) | To | From |
| Pump payment | Petrol pump | Cash/Bank |
| Expense | Expense head (naya bhi type kar sakte ho) | Cash/Bank |
| Expense on pump credit (apni gaadi ka diesel etc.) | Expense head | Petrol pump |
| Other payment | Koi bhi account | Cash/Bank |
| Other receipt | Cash/Bank | Koi bhi account |
| Diesel to truck (trip) | Truck owner | Petrol pump |

## Party Receipt (truck-wise, bank mein)
Party ek baar bank transfer karti hai — ek truck ka ya kai trucks ka ek saath.
1. Party chuno → **bank mein kitna aaya** (amount, bank, date, UTR).
2. Party ki pending trips truck-wise dikhti hain (truck, trip, GR, balance) → har truck ke aage amount likho, ya **⚡ Auto-fill** (purani trip pehle, har trip ke balance tak).
3. Jo bach jaaye = **On account** (party ka advance, kisi truck se nahi juda).
4. Har truck line: **Bank Dr / Party Cr**, trip se linked → trip-wise party balance sahi.
   Line se trip ka balance poora ho jaaye = BALANCE, warna ADVANCE.
5. Ek transfer ki saari lines ka ek **batch no.** → Bank Book mein **ek hi line** (bank statement jaisi). Cancel karo toh poora transfer ek saath cancel.
6. Truck-wise total, aaye hue amount se zyada nahi ho sakta. Kisi truck mein balance se zyada daala toh warning (party advance maana jaayega).

## Hisaab Check (logic verification)
App in cheezon ko khud check karta hai:
1. Har entry: Debit = Credit
2. Trip bill (freight, hire, commission, shortage) = aaj ke formula se (galat ho toh "Rebuild" button)
3. POD se pehle truck balance payment nahi
4. Truck ko hire se zyada payment nahi; party se freight se zyada receipt nahi
5. Loaded trip mein dono rate bhare hon
6. Ek truck do chalti trips mein nahi
7. Cash kabhi minus nahi
8. Owner / Party ledger = uski trips ke balance ka jod + opening + bina-trip entries
9. 15 din se purani pending POD (reminder)

## Review (Nov 2026) — safety rules added
- **Date India time (IST)** se: server UTC par chalta hai, raat 12 se 5:30 ke beech pehle "kal" ki date lagti thi.
- **Truck / party badalna**: agar trip mein advance/diesel (truck) ya receipt (party) ho chuki hai, toh truck ya party nahi badlegi — pehle wo entries cancel karo. (Warna paisa purane owner ke khate mein aur trip naye owner ki — hisaab do jagah bat jaata.)
- **Edit history**: har trip banana/badalna/cancel aur har entry banana/cancel — kisne, kab, kya badla (Settings → Edit history).
- **Backup**: Settings → saari tables ek zip mein download.
- **Profit & Loss**: trips + office kharche, period-wise.
- **Owner ko ek transfer, kai trips**: Cash/Bank Entry → "Owner: many trips" (POD wali pehle).
- **Advance adjust**: party ka "on account" advance ya owner ko bina trip diya advance → baad mein kisi trip mein jodo (Advance Adjustment clearing account se; paisa dobara nahi hilta, dono entries saath cancel hoti hain).

## Message se trip (paste)
- Rule-based (internet / AI kharcha nahi), aapke Masters se milaan.
- Truck: RJ14AB1234 / "RJ 14 AB 1234" / sirf last 4 digit (agar ek hi truck mile). Masters mein nahi toh warning.
- Route: "A se B", "A to B", "A -> B", "unload: B" — direction inhi shabdon se.
- Rate: "party rate / freight / fright" = freight; "gaadi bhada / truck rate / hire / भाड़ा" = truck rate.
  Bina label ke do rate → bada = freight, chhota = truck (warning ke saath).
- Weight: "25 ton / 25 MT / 25 टन / wt 25". GR: "GR / LR / bilty". Advance: "adv / advance".
- Sirf form bharta hai — Save aap khud karte ho.

## Extra rules in v1
- Entries kabhi delete nahi hoti — sirf **cancel with reason** (cancelled bhi dikhti hain).
- Trip ka bill (freight / hire / commission / shortage) trip edit karte hi apne aap dobara banta hai.
- Party receipt aur truck payment ek saath kai trips mein baant sakte hain; truck payment mein POD aayi trip = BALANCE, baaki = ADVANCE.
- Party se "On account" (bina trip) receipt bhi ho sakti hai.
- Trip cancel: sirf loading se pehle aur jab koi payment/diesel entry na ho.
- Bulk upload: file ka naam = GR No. (4521.pdf, GR-4521.pdf, 4521_POD.pdf) → app khud sahi trip mein jodta hai.
