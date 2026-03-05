#!/usr/bin/env python3
"""
Upload car photos from md files to Cloudflare R2 using AWS CLI,
and rewrite photo URLs in-place.

Usage example:
  python3 scripts/local_sync_website_photos_to_r2_update_md.py \
    --cars-dir ./_cars \
    --bucket "bucket" \
    --public-base-url "https://<domain>" \
    --endpoint-url https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com \
    --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import random
import string
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse, quote
from urllib.request import urlopen, Request


FRONT_MATTER_RE = re.compile(r"(?s)^\s*---\s*\n(.*?)\n---\s*\n(.*)$")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def extract_title_and_photos(text: str) -> Tuple[Optional[str], List[str]]:
    """
    Minimal extractor for:
      title: ...
      photos:
        - ...
        - ...
    Works for common Jekyll front matter and simple YAML blocks.
    """
    title = None
    photos: List[str] = []
    lines = text.splitlines()

    for line in lines:
        m = re.match(r"^\s*title\s*:\s*(.+?)\s*$", line)
        if m:
            title = m.group(1).strip().strip('"').strip("'").strip()
            break

    photos_start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*photos\s*:\s*$", line):
            photos_start = i
            break

    if photos_start is None:
        return title, photos

    for j in range(photos_start + 1, len(lines)):
        line = lines[j]

        # stop at next top-level key like "price_usd:" if not indented
        if re.match(r"^[A-Za-z0-9_]+\s*:\s*", line) and not line.startswith((" ", "\t")):
            break

        m = re.match(r"^\s*-\s*(\S.+?)\s*$", line)
        if m:
            url = m.group(1).strip().strip('"').strip("'")
            if url:
                photos.append(url)

    return title, photos


def get_yaml_area(full_text: str) -> str:
    """
    If Jekyll front matter exists, returns just YAML block; else returns whole file.
    """
    m = FRONT_MATTER_RE.match(full_text)
    if m:
        return m.group(1)
    return full_text


def get_extension_from_url(url: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix and re.match(r"^\.[a-z0-9]{1,5}$", suffix):
        return suffix
    return ".jpg"


def make_key(title: str, idx: int, ext: str) -> str:
    # keep title as-is for "path separated by title"
    t = title.strip().strip("/")
    return f"cars/{t}/{idx}{ext}"


def build_public_url(public_base_url: str, key: str) -> str:
    base = public_base_url.rstrip("/")
    encoded = "/".join(quote(seg, safe="") for seg in key.split("/"))
    return f"{base}/{encoded}"


def download_file(url: str, timeout: int):
    """
    Download file.
    Returns (temp_file_path, content_type)
    """
    req = Request(url, headers={"User-Agent": "autowelt-r2-uploader/1.0"})
    
    with urlopen(req, timeout=timeout) as r:
        content_type = r.headers.get("Content-Type")
        if content_type:
            content_type = content_type.split(";")[0].strip()

        fd, tmp_path = tempfile.mkstemp(prefix="r2img_", suffix=".bin")
        os.close(fd)
        tmp = Path(tmp_path)

        with tmp.open("wb") as f:
            f.write(r.read())

    return tmp, content_type


def aws_s3_cp(
    local_path: Path,
    bucket: str,
    key: str,
    endpoint_url: str,
    profile: Optional[str],
    #cache_control: Optional[str],
    content_type: Optional[str],
    dry_run: bool,
) -> None:
    """
    Runs:
      aws s3 cp <file> s3://bucket/key --endpoint-url ... [--profile ...] [--cache-control ...] [--content-type ...]
    """
    cmd = ["aws", "s3", "cp", str(local_path), f"s3://{bucket}/{key}", "--endpoint-url", endpoint_url]
    if profile:
        cmd += ["--profile", profile]
    #if cache_control:
    #    cmd += ["--cache-control", cache_control]
    if content_type:
        cmd += ["--content-type", content_type]

    if dry_run:
        print("        AWS:", " ".join(cmd))
        return

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"aws s3 cp failed: {res.stderr.strip() or res.stdout.strip()}")


def rewrite_photo_urls(full_text: str, old_urls: List[str], new_urls: List[str]) -> str:
    """
    Replace only list item lines matching old URLs, preserving order and avoiding global replace.
    """
    if len(old_urls) != len(new_urls):
        raise ValueError("URL list length mismatch")

    mapping = dict(zip(old_urls, new_urls))
    lines = full_text.splitlines(True)
    out = []

    for line in lines:
        # match "- <url>" with indentation
        stripped = line.rstrip("\n").rstrip("\r")
        m = re.match(r"^(\s*-\s*)(\S.+?)(\s*)$", stripped)
        if m:
            prefix, url, suffix = m.group(1), m.group(2), m.group(3)
            url_clean = url.strip().strip('"').strip("'")
            if url_clean in mapping:
                replaced = mapping[url_clean]
                # preserve quoting style if any
                if url.strip().startswith('"') and url.strip().endswith('"'):
                    replaced = f'"{replaced}"'
                elif url.strip().startswith("'") and url.strip().endswith("'"):
                    replaced = f"'{replaced}'"
                out.append(f"{prefix}{replaced}{suffix}\n")
                continue

        out.append(line)

    return "".join(out)


def ensure_aws_cli_available() -> None:
    try:
        subprocess.run(["aws", "--version"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("ERROR: aws CLI not found. Install AWS CLI first.", file=sys.stderr)
        sys.exit(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cars-dir", default="./_cars", help="Path to _cars folder (default: ./_cars)")
    ap.add_argument("--bucket", required=True, help="R2 bucket name")
    ap.add_argument("--endpoint-url", required=True, help="R2 endpoint URL (https://<accountid>.r2.cloudflarestorage.com)")
    ap.add_argument("--public-base-url", required=True, help="Public base URL for images (e.g. https://images.autowelt.lviv.ua)")
    ap.add_argument("--profile", default=None, help="AWS CLI profile name (optional)")
    ap.add_argument("--timeout", type=int, default=60, help="Download timeout seconds (default 60)")
    #ap.add_argument("--cache-control", default="public, max-age=31536000, immutable", help="Cache-Control for uploads")
    ap.add_argument("--dry-run", action="store_true", help="Print actions, don't upload or modify files")
    args = ap.parse_args()

    ensure_aws_cli_available()

    cars_dir = Path(args.cars_dir)
    if not cars_dir.exists() or not cars_dir.is_dir():
        print(f"ERROR: cars dir not found: {cars_dir}", file=sys.stderr)
        sys.exit(2)

    md_files = sorted(cars_dir.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {cars_dir}")
        return

    for md in md_files:
        full_text = read_text(md)

        yaml_area = get_yaml_area(full_text)
        title, photos = extract_title_and_photos(yaml_area)

        if not title:
            print(f"[SKIP] {md.name}: no title found")
            continue
        if not photos:
            print(f"[SKIP] {md.name}: no photos found")
            continue
        
        # Add 4 random letters to title to mitigate colissions
        suffix = ''.join(random.choices(string.ascii_lowercase, k=4))
        title = f"{title} {suffix}"

        print(f"\n=== {md.name} ===")
        print(f"Title: {title}")
        print(f"Photos: {len(photos)}")

        new_urls: List[str] = []
        temp_paths: List[Path] = []

        try:
            for idx, url in enumerate(photos, start=1):
                ext = get_extension_from_url(url)
                key = make_key(title, idx, ext)
                new_url = build_public_url(args.public_base_url, key)
                new_urls.append(new_url)

                print(f"  [{idx}/{len(photos)}] {url}")
                print(f"        -> s3://{args.bucket}/{key}")
                print(f"        -> {new_url}")

                if args.dry_run:
                    # show the aws command too
                    aws_s3_cp(
                        local_path=Path("/tmp/file"),  # dummy
                        bucket=args.bucket,
                        key=key,
                        endpoint_url=args.endpoint_url,
                        profile=args.profile,
                        #cache_control=args.cache_control,
                        content_type=None,
                        dry_run=True,
                    )
                    continue

                tmp, ctype = download_file(url, timeout=args.timeout)
                temp_paths.append(tmp)

                aws_s3_cp(
                    local_path=tmp,
                    bucket=args.bucket,
                    key=key,
                    endpoint_url=args.endpoint_url,
                    profile=args.profile,
                    #cache_control=args.cache_control,
                    content_type=ctype,
                    dry_run=False,
                )

            if args.dry_run:
                continue

            new_text = rewrite_photo_urls(full_text, photos, new_urls)

            write_text(md, new_text)
            print(f"Updated {md.name}")
            # backup once
            #backup = md.with_suffix(md.suffix + ".bak")
            #if not backup.exists():
            #    md.replace(backup)
            #    write_text(md, new_text)
            #    print(f"Updated {md.name} (backup: {backup.name})")
            #else:
            #    write_text(md, new_text)
            #    print(f"Updated {md.name} (backup already existed)")

        except Exception as e:
            print(f"[ERROR] {md.name}: {e}", file=sys.stderr)

        finally:
            for p in temp_paths:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass


if __name__ == "__main__":
    main()