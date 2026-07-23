"""Upload rendered page JPEGs to an S3-compatible object store (Cloudflare R2).

Runs locally, once, to seed the bucket the deployed API redirects to. The keys
match `app.api.routes.filings.page_image_key`:
    filings/{accession_nodash}/pages/page_{n:04d}.jpg
and the on-disk layout already nests images as
    {storage_dir}/filings/{accession_nodash}/pages/page_NNNN.jpg
so the key is just the path relative to `{storage_dir}` with forward slashes.

Works with any S3-compatible store (Supabase Storage, Cloudflare R2, AWS S3);
boto3 is intentionally NOT a project dependency (the server never touches S3).
Run with uv's ephemeral install, supplying the store's S3 endpoint + creds:

    # Supabase Storage (S3 endpoint + keys from Project Settings -> Storage)
    S3_ENDPOINT_URL=https://<ref>.storage.supabase.co/storage/v1/s3 \
    S3_REGION=<project-region> \
    S3_ACCESS_KEY_ID=... S3_SECRET_ACCESS_KEY=... S3_BUCKET=findoc-pages \
        uv run --with boto3 python scripts/upload_images.py

    # Cloudflare R2
    S3_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com \
    S3_ACCESS_KEY_ID=... S3_SECRET_ACCESS_KEY=... S3_BUCKET=findoc-pages \
        uv run --with boto3 python scripts/upload_images.py

Flags:
    --storage-dir data     # root holding filings/ (default: STORAGE_DIR or ./data)
    --dry-run              # list what would upload, touch nothing
    --overwrite            # re-put objects that already exist (default: skip)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    default_dir = os.environ.get("STORAGE_DIR", "./data")
    parser.add_argument("--storage-dir", default=default_dir)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        sys.exit(f"missing required env var: {name}")
    return val


def make_client() -> tuple[object, str]:
    bucket = require_env("S3_BUCKET")
    # R2 accepts region "auto"; Supabase/AWS want the real project region.
    region = os.environ.get("S3_REGION", "auto").strip() or "auto"
    client = boto3.client(
        "s3",
        endpoint_url=require_env("S3_ENDPOINT_URL"),
        aws_access_key_id=require_env("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=require_env("S3_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4", region_name=region),
    )
    return client, bucket


def object_exists(client: object, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)  # type: ignore[attr-defined]
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def main() -> None:
    args = build_parser().parse_args()
    root = Path(args.storage_dir).expanduser()
    filings_root = root / "filings"
    if not filings_root.is_dir():
        sys.exit(f"no filings dir under {filings_root}")

    images = sorted(filings_root.glob("*/pages/page_*.jpg"))
    if not images:
        sys.exit(f"no page images found under {filings_root}")

    client: object
    bucket: str
    if args.dry_run:
        client, bucket = None, "<dry-run>"  # type: ignore[assignment]
    else:
        client, bucket = make_client()

    uploaded = skipped = 0
    for path in images:
        # key = path relative to storage_dir, forward slashes:
        #   filings/{accession_nodash}/pages/page_NNNN.jpg
        key = path.relative_to(root).as_posix()
        if args.dry_run:
            print(f"WOULD PUT {key}")
            uploaded += 1
            continue
        if not args.overwrite and object_exists(client, bucket, key):
            skipped += 1
            continue
        client.upload_file(  # type: ignore[attr-defined]
            str(path), bucket, key, ExtraArgs={"ContentType": "image/jpeg"}
        )
        uploaded += 1
        if uploaded % 100 == 0:
            print(f"  ...{uploaded} uploaded")

    print(f"done: {uploaded} uploaded, {skipped} skipped ({len(images)} local)")


if __name__ == "__main__":
    main()
