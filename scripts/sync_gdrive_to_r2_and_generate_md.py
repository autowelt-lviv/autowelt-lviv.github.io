import os
import re
import json
import shutil
import subprocess
import unicodedata
from typing import Dict, List, Optional
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.auth import default

REPO_ROOT = Path(__file__).resolve().parents[1]
CARS_MD_DIR = REPO_ROOT / "_cars"
WORK_DIR = REPO_ROOT / ".work"

R2_ACCOUNT_ID = os.environ["R2_ACCOUNT_ID"]
R2_BUCKET = os.environ["R2_BUCKET"]
R2_PUBLIC_BASE_URL = os.environ["R2_PUBLIC_BASE_URL"].rstrip("/")
GDRIVE_FOLDER_ID = os.environ["GDRIVE_FOLDER_ID"]

R2_ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# --------- Google Drive: internal helpers (used by the 3 functions) ---------

def _list_children(
    drive,
    parent_id: str,
    *,
    only_folders: bool = False,
    only_files: bool = False,
    verbose: bool = False,
) -> List[Dict]:
    """
    List direct children of a Drive folder (handles pagination).
    Returns list of dicts with keys like: id, name, mimeType, size
    """
    if only_folders and only_files:
        raise ValueError("only_folders and only_files can't both be True")

    q = [f"'{parent_id}' in parents", "trashed=false"]
    if only_folders:
        q.append("mimeType='application/vnd.google-apps.folder'")
    if only_files:
        q.append("mimeType!='application/vnd.google-apps.folder'")
    query = " and ".join(q)

    fields = "nextPageToken, files(id, name, mimeType, size)"
    out: List[Dict] = []
    page_token: Optional[str] = None

    while True:
        resp = (
            drive.files()
            .list(
                q=query,
                fields=fields,
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        if verbose:
            print(resp)
        out.extend(resp.get("files", []) or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return out

def _find_child_folder_id(drive, parent_id: str, child_name: str) -> Optional[str]:
    """
    Find a direct child folder with exact name under parent_id.
    """
    for item in _list_children(drive, parent_id, only_folders=True):
        if item.get("name") == child_name:
            return item.get("id")
    return None

def _download_file(drive, file_id: str, dest_path: Path) -> None:
    """
    Download a single Drive file (by id) to dest_path.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)

    with dest_path.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()

# --------- Google Drive functions ---------

def list_gdrive_car_folders(drive, gdrive_root_folder_id: str) -> List[str]:
    """
    Expects structure:
      <gdrive_root_folder_id>/
        cars/
          <car-folder-1>/
          <car-folder-2>/
    Returns sorted list of car folder names under cars/.
    """
    cars_id = _find_child_folder_id(drive, gdrive_root_folder_id, "cars")
    if not cars_id:
        raise RuntimeError("Could not find a 'cars' folder under the provided root folder ID.")

    car_folders = _list_children(drive, cars_id, only_folders=True)
    return sorted([f["name"] for f in car_folders if f.get("name")])


def list_gdrive_photos_for_folder(
    drive,
    gdrive_root_folder_id: str,
    car_folder_name: str,
) -> List[str]:
    """
    Lists file names inside:
      <root>/cars/<car_folder_name>/
    Returns sorted list of filenames (no recursion).
    """
    cars_id = _find_child_folder_id(drive, gdrive_root_folder_id, "cars")
    if not cars_id:
        raise RuntimeError("Could not find a 'cars' folder under the provided root folder ID.")

    car_folder_id = _find_child_folder_id(drive, cars_id, car_folder_name)
    if not car_folder_id:
        raise RuntimeError(f"Could not find car folder '{car_folder_name}' under 'cars/'.")

    files = _list_children(drive, car_folder_id, only_files=True)
    return sorted([f["name"] for f in files if f.get("name")])


def copy_gdrive_folder_local(
    drive,
    gdrive_root_folder_id: str,
    car_folder_name: str,
    dst_dir: Path,
) -> None:
    """
    Downloads the contents of:
      <root>/cars/<car_folder_name>/
    into:
      dst_dir

    Recurses into subfolders if they exist.
    """
    cars_id = _find_child_folder_id(drive, gdrive_root_folder_id, "cars")
    if not cars_id:
        raise RuntimeError("Could not find a 'cars' folder under the provided root folder ID.")

    car_folder_id = _find_child_folder_id(drive, cars_id, car_folder_name)
    if not car_folder_id:
        raise RuntimeError(f"Could not find car folder '{car_folder_name}' under 'cars/'.")

    target_root = dst_dir
    target_root.mkdir(parents=True, exist_ok=True)

    # Download files in this folder
    for f in _list_children(drive, car_folder_id, only_files=True):
        _download_file(drive, f["id"], target_root / f["name"])

# --------- End. Google Drive functions ---------

def run(cmd: list[str], *, check=True, capture=True, text=True, env=None, cwd=None, verbose=False) -> subprocess.CompletedProcess:
    if verbose:
        print(">>", " ".join(cmd))
    p = subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=text,
        env=env,
        cwd=cwd,
    )
    if verbose:
        if p.returncode:
            if p.returncode != 0:
                print("return code:", p.returncode)
                print("stdout:\n", p.stdout)
                print("stderr:\n", p.stderr)
    return p

def slugify(name: str) -> str:
    # Keep readable filenames, but safer for git files
    s = unicodedata.normalize("NFKC", name).strip()
    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-_.]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or 'car'

def ensure_dirs():
    CARS_MD_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

def list_r2_car_folders() -> list[str]:
    """
    List prefixes (folders) under s3://bucket/cars/
    We use aws s3api list-objects-v2 with Delimiter='/'
    """
    res = run([
        "aws", "--endpoint-url", R2_ENDPOINT,
        "s3api", "list-objects-v2",
        "--bucket", R2_BUCKET,
        "--prefix", "cars/",
        "--delimiter", "/",
    ])
    data = json.loads(res.stdout or "{}")
    prefixes = data.get("CommonPrefixes", []) or []
    # prefix looks like "cars/BMW5 tdi2.0 supreme/"
    names = []
    for p in prefixes:
        pref = p.get("Prefix", "")
        if pref.startswith("cars/"):
            rest = pref[len("cars/"):]
            rest = rest.rstrip("/")
            if rest:
                names.append(rest)
    return sorted(set(names))

def sync_local_to_r2(local_folder: Path, folder_name: str):
    # Upload to s3://bucket/cars/<folder_name>/
    run([
        "aws", "--endpoint-url", R2_ENDPOINT,
        "s3", "sync",
        local_folder.as_posix(),
        f"s3://{R2_BUCKET}/cars/{folder_name}/",
        "--no-progress",
    ])

def make_photo_url(folder_name: str, filename: str) -> str:
    # URL-encode per path segment to keep spaces safe
    return f"{R2_PUBLIC_BASE_URL}/cars/{quote(folder_name)}/{quote(filename)}"

def create_md(folder_name: str, photo_files: list[str]) -> Path:
    now = datetime.now(timezone.utc)
    # Example datetime in filename: 20260101123030
    file_dt = now.strftime("%Y%m%d%H%M%S")
    iso_dt = now.isoformat(timespec="milliseconds")
    slug_name = slugify(folder_name)
    md_path = CARS_MD_DIR / f"{slug_name}-{file_dt}.md"

    urls = [make_photo_url(folder_name, f) for f in photo_files]

    # YAML front matter (simple + compatible with Jekyll/Eleventy)
    lines = []
    lines.append("---")
    lines.append('layout: car')
    lines.append('post_hidden: true')
    lines.append(f'created_at: {iso_dt}')
    safe_title = folder_name.replace('"', '\\"')
    lines.append(f'title: {safe_title}')
    lines.append('under_deposit: false')
    lines.append('on_site: true')
    lines.append("photos:")
    for u in urls:
        lines.append(f'  - {u}')
    lines.append("---")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path

def main():
    creds, _ = default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    ensure_dirs()

    # Clean working folder each run
    if WORK_DIR.exists():
        for p in WORK_DIR.iterdir():
            if p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    gdrive_folders = list_gdrive_car_folders(drive, GDRIVE_FOLDER_ID)
    r2_folders = list_r2_car_folders()

    gdrive_set = set(gdrive_folders)
    r2_set = set(r2_folders)

    missing_on_r2 = sorted(list(gdrive_set - r2_set))

    print(f"GDrive folders: {len(gdrive_folders)}")
    print(f"R2 folders: {len(r2_folders)}")
    print(f"Missing on R2: {len(missing_on_r2)}")
    for folder_name in missing_on_r2:
        print(folder_name)

    # For each missing folder:
    # 1) download locally
    # 2) upload to R2
    # 3) generate md with URLs
    for folder_name in missing_on_r2:
        local_dst = WORK_DIR / "cars" / folder_name
        copy_gdrive_folder_local(drive, GDRIVE_FOLDER_ID, folder_name, local_dst)
        sync_local_to_r2(local_dst, folder_name)

        photo_files = list_gdrive_photos_for_folder(drive, GDRIVE_FOLDER_ID, folder_name)
        md = create_md(folder_name, photo_files)
        print("Created:", md.relative_to(REPO_ROOT))

if __name__ == "__main__":
    main()