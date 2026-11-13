"""Backup: every table as CSV in one zip. Manual download (Settings) + automatic daily copy to Google Drive.

Auto backup runs on the first app open of each day (Streamlit has no timer). It takes a few seconds,
keeps the last KEEP zips in '<Drive main folder>/Backups', and never stops the app if it fails.
"""
import io
import zipfile

from core import clock, db

TABLES = ("settings", "accounts", "trucks", "lookups", "trips", "vouchers", "ledger_entries", "trip_documents",
          "bills", "followups", "audit_log")
KEEP = 30


def make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for tbl in TABLES:
            try:
                rows = db._query_now(f"select * from {tbl} order by 1")       # fresh, not from the cache
                import pandas as pd
                z.writestr(f"{tbl}.csv", pd.DataFrame(rows).to_csv(index=False))
            except Exception as e:  # table may not exist on an old database
                z.writestr(f"{tbl}_ERROR.txt", str(e))
    return buf.getvalue()


def file_name() -> str:
    return f"transport_backup_{clock.now():%Y-%m-%d_%H%M}.zip"


def to_drive(data: bytes, name: str) -> str:
    """Upload one backup zip to Drive and delete the oldest beyond KEEP. Returns the Drive file id."""
    from googleapiclient.http import MediaIoBaseUpload

    from core import drive
    svc = drive._service()
    folder = drive._folder("Backups")
    f = svc.files().create(body={"name": name, "parents": [folder]},
                           media_body=MediaIoBaseUpload(io.BytesIO(data), mimetype="application/zip"),
                           fields="id").execute()
    old = svc.files().list(q=f"'{folder}' in parents and trashed = false and name contains 'transport_backup_'",
                           orderBy="createdTime desc", fields="files(id)", pageSize=200).execute().get("files", [])
    for x in old[KEEP:]:
        try:
            svc.files().update(fileId=x["id"], body={"trashed": True}).execute()
        except Exception:
            pass
    return f["id"]


def due() -> bool:
    last = (db.setting("last_auto_backup", "") or "")[:10]
    return last != str(clock.today())


def auto_if_due() -> str | None:
    """Called once per session after login. Returns a short status text, or None when nothing was done."""
    from core import drive
    if not drive.configured() or not due():
        return None
    # mark first, so two phones opening at once do not both upload, and a failure is not retried every click
    db.save_setting("last_auto_backup", f"{clock.today()} (running)")
    try:
        name = file_name()
        to_drive(make_zip(), name)
        db.save_setting("last_auto_backup", f"{clock.today()} {clock.now():%H:%M} ok {name}")
        return f"Aaj ka backup Drive par save: {name}"
    except Exception as e:
        db.save_setting("last_auto_backup", f"{clock.today()} FAILED {str(e)[:150]}")
        return f"Auto backup nahi hua: {str(e)[:150]}"
