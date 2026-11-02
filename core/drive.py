"""Google Drive storage for GR / POD copies.

Uses the 'drive.file' scope: the app can only see files and folders it created itself,
so it never touches anything else in your Drive.
Folder layout:  <Transport Docs> / 2026 / 11-Nov / T-0001 / file
"""
import io
import re

import streamlit as st
from PIL import Image, ImageOps

from core import clock, db

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def configured() -> bool:
    g = st.secrets.get("google_drive", {})
    return all(g.get(k) for k in ("client_id", "client_secret", "refresh_token"))


@st.cache_resource(show_spinner=False)
def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    g = st.secrets["google_drive"]
    creds = Credentials(None, refresh_token=g["refresh_token"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=g["client_id"], client_secret=g["client_secret"], scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_or_create(name: str, parent_id: str | None) -> str:
    svc = _service()
    safe = name.replace("'", "\\'")
    q = f"name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    q += f" and '{parent_id}' in parents" if parent_id else " and 'root' in parents"
    found = svc.files().list(q=q, fields="files(id)", spaces="drive").execute().get("files", [])
    if found:
        return found[0]["id"]
    meta = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        meta["parents"] = [parent_id]
    return svc.files().create(body=meta, fields="id").execute()["id"]


def _folder(path: str) -> str:
    """Folder id for a path like '' (root), '2026', '2026/11-Nov', '2026/11-Nov/T-0001'. Cached in DB."""
    row = db.one("select folder_id from drive_folders where path = %s", (path,))
    if row:
        return row["folder_id"]
    if path == "":
        fid = _find_or_create(db.setting("drive_root_folder_name", "Transport Docs"), None)
    else:
        parent_path, _, name = path.rpartition("/")
        fid = _find_or_create(name, _folder(parent_path))
    db.execute("insert into drive_folders(path, folder_id) values (%s, %s) "
               "on conflict (path) do update set folder_id = excluded.folder_id", (path, fid))
    return fid


def trip_folder_path(trip: dict) -> str:
    d = trip.get("loading_date") or trip.get("booking_date") or clock.today()
    return f"{d.year}/{d.month:02d}-{MONTHS[d.month - 1]}/{trip['trip_no']}"


def compress_image(data: bytes, max_side: int = 1800, quality: int = 70) -> bytes:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def prepare_file(name: str, data: bytes, mime: str) -> tuple[str, bytes, str]:
    """Compress photos to JPEG; PDFs and other files go as they are."""
    if (mime or "").startswith("image/"):
        try:
            data = compress_image(data)
            name = re.sub(r"\.[^.]+$", "", name) + ".jpg"
            mime = "image/jpeg"
        except Exception:
            pass
    return name, data, mime


def upload(trip: dict, doc_type: str, name: str, data: bytes, mime: str, uploaded_by: str) -> dict:
    from googleapiclient.http import MediaIoBaseUpload

    name, data, mime = prepare_file(name, data, mime)
    folder_id = _folder(trip_folder_path(trip))
    gr = f"_GR-{trip['gr_no']}" if trip.get("gr_no") else ""
    drive_name = f"{trip['trip_no']}{gr}_{doc_type}_{name}"
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime or "application/octet-stream",
                              resumable=len(data) > 5 * 1024 * 1024)
    f = _service().files().create(body={"name": drive_name, "parents": [folder_id]},
                                  media_body=media, fields="id, webViewLink").execute()
    row = db.execute(
        "insert into trip_documents (trip_id, doc_type, file_name, mime_type, size_bytes, "
        "drive_file_id, drive_link, uploaded_by) values (%s,%s,%s,%s,%s,%s,%s,%s) returning *",
        (trip["id"], doc_type, drive_name, mime, len(data), f["id"], f.get("webViewLink"), uploaded_by))
    return row


def trash(doc_id: int, reason: str):
    doc = db.one("select * from trip_documents where id = %s", (doc_id,))
    if not doc or doc["is_deleted"]:
        return
    try:
        _service().files().update(fileId=doc["drive_file_id"], body={"trashed": True}).execute()
    except Exception:
        pass   # file may already be gone from Drive; still mark it deleted here
    db.execute("update trip_documents set is_deleted = true, delete_reason = %s where id = %s",
               (reason, doc_id))


def download(drive_file_id: str) -> bytes:
    return _service().files().get_media(fileId=drive_file_id).execute()


def test_connection() -> str:
    fid = _folder("")
    return fid


# ---------- Bulk upload helpers ----------

GR_PREFIX = re.compile(r"^(GR\s*NO\.?|G\.R\.|GR)[\s._\-:#]*", re.I)


def gr_from_filename(filename: str) -> str:
    """'GR-4521.pdf' -> '4521', 'gr_4521_pod.pdf' -> '4521', '4521 (2).pdf' -> '4521'."""
    stem = re.sub(r"\.[^.]+$", "", filename).strip()
    stem = GR_PREFIX.sub("", stem)
    stem = re.sub(r"\s*\(\d+\)$", "", stem)                         # "(2)" copies
    stem = re.split(r"[\s_]+(?:POD|GR|COPY|PAGE\s*\d*|P\d+)\b", stem, flags=re.I)[0]
    return stem.strip(" ._-").upper()


def doc_type_from_filename(filename: str, default: str) -> str:
    return "POD" if "POD" in filename.upper() else default


def match_key(s: str) -> str:
    """Compare GR numbers on letters+digits only: 'RJ-4521' == 'rj 4521' == 'RJ4521'."""
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())
