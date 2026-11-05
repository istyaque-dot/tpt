# ⚡ App ko India server par chalana (tez + kabhi nahi soyegi)

**Kyun:** abhi app America (Streamlit Cloud) mein aur database Ireland (eu-west-1) mein hai — har click par
data duniya ka chakkar lagata hai. Dono India (Mumbai) mein honge to app turant khulegi.

## Kadam 1 — Database Mumbai mein (abhi karo, data kam hai)
1. Supabase → **New project** → Region **South Asia (Mumbai) ap-south-1**.
2. SQL Editor → `schema.sql` chalao.
3. Purana data chahiye to: purani app → Settings → **Backup** download karo (sirf test trips hain to naya shuru karna aasaan hai).
4. Secrets ke `[database]` mein naye project ka host / user / password daalo (Connect → Shared pooler).
   *(Sirf ye kadam bhi speed kaafi badha dega, server badle bina bhi.)*

## Kadam 2 — Server (VPS) Mumbai / Bangalore region mein
Koi bhi chhota Linux server: 1 CPU, 1–2 GB RAM, Ubuntu 24.04 — jaise AWS Lightsail (Mumbai),
DigitalOcean (Bangalore), Hostinger VPS (India). Mahine ka kuch sau rupaye. Petrol pump app bhi isi par chal sakti hai.

## Kadam 3 — Server par app chalao (ek baar)
Server par SSH se login karke:
```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/<aapka-username>/tpt.git transport_app
cd transport_app/deploy
nano secrets.toml        # Streamlit Cloud wale Secrets yahan paste karo, Save (Ctrl+O, Enter, Ctrl+X)
```
Domain (HTTPS ke liye):
- Apna domain ho to uska A-record server ke IP par daalo, aur `DOMAIN=app.aapkadomain.com`.
- Domain nahi hai to free: server IP `1.2.3.4` ho to `DOMAIN=1-2-3-4.sslip.io`.
```bash
echo "DOMAIN=1-2-3-4.sslip.io" > .env
docker compose up -d --build
```
App khulegi: `https://1-2-3-4.sslip.io` (padlock ke saath). Phone par Add to Home screen dobara karo.

## Naya version daalna
GitHub par files upload karne ke baad server par:
```bash
cd ~/transport_app && git pull && cd deploy && docker compose up -d --build
```

## Dhyan rakho
- `secrets.toml` sirf server par — GitHub par kabhi nahi.
- Backup (Settings → Backup) har hafte lete raho.
- Streamlit Cloud wali app tab tak chalne do jab tak server wali theek na chal jaaye.
