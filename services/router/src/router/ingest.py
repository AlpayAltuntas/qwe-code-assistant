"""Ingestion pipeline: staging -> explicit promotion -> checksum -> chunk -> embed -> Chroma.

Mitigates docs/threat-model.md T1 (RAG corpus poisoning): new docs land
in an untrusted staging folder first; nothing reaches the trusted
corpus (and therefore nothing is retrievable) without an explicit
`promote` step; every promoted doc is checksummed and logged.

NOTE on scope: the threat model's full mitigation additionally calls
for running ingestion inside the Docker sandbox used elsewhere in the
project. That sandbox doesn't exist yet — it's built in Phase 4
alongside the EDI tool functions. Until then, treat `promote`/`index`
as trusted-operator actions (you are choosing to parse a document you
already reviewed), not as safe-by-construction against a malicious
file.
"""

import argparse
import hashlib
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path

import httpx

from router.config import CORPUS_DIR, MANIFEST_PATH, STAGING_DIR
from router.embeddings import embed
from router.logging_utils import log_ingest_event
from router.vectorstore import upsert_chunks

DOMAIN_SUBDIR = "edi"
COLLECTION_NAME = "edi_specs"
EMBED_BATCH_SIZE = 64

# Public, redistributable spec sources for the Phase 3 corpus scope:
# EDIFACT INVOIC + UBL Invoice. See docs/architecture.md.
SOURCES: list[tuple[str, str]] = [
    (
        "edifact_d01b_invoic.html",
        "https://www.edifactory.de/edifact/directory/D01B/message/INVOIC",
    ),
    (
        "ubl_2.1_invoice.xsd",
        "https://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/maindoc/UBL-Invoice-2.1.xsd",
    ),
    (
        "ubl_2.1_common_aggregate_components.xsd",
        "https://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/common/UBL-CommonAggregateComponents-2.1.xsd",
    ),
    (
        "ubl_2.1_common_basic_components.xsd",
        "https://docs.oasis-open.org/ubl/os-UBL-2.1/xsd/common/UBL-CommonBasicComponents-2.1.xsd",
    ),
]

# The CII (Cross Industry Invoice) schema used by ZUGFeRD/Factur-X — see
# Phase 5. Unlike the sources above, the annotated version (with real
# per-element documentation, not just structure) isn't published at a
# stable direct URL; it's only distributed inside the `factur-x` PyPI
# package's sdist. Fetched by extracting one file from that tarball
# rather than a plain GET — see _fetch_cii_schema.
_FACTURX_SDIST_URL = (
    "https://files.pythonhosted.org/packages/d2/b1/"
    "678c0299a1b1fba356001645451868eab967c79a050e23b81ac21c74d038/"
    "factur_x-6.7.tar.gz"
)
_FACTURX_SDIST_MEMBER = (
    "factur_x-6.7/src/facturx/xsd_and_schematron/cii-extended-ctc-fr/"
    "CrossIndustryInvoice_100pD22B_urn_un_unece_uncefact_data_standard_"
    "ReusableAggregateBusinessInformationEntity_100.xsd"
)
CII_FILENAME = "cii_100pd22b_reusable_aggregate_business_information_entity.xsd"

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; qwe-code-assistant-ingest/0.1)"}


def _fetch_cii_schema(dest_dir: Path) -> None:
    response = httpx.get(_FACTURX_SDIST_URL, headers=_HEADERS, timeout=60.0, follow_redirects=True)
    response.raise_for_status()
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
        member = tar.getmember(_FACTURX_SDIST_MEMBER)
        content = tar.extractfile(member).read()
    dest = dest_dir / CII_FILENAME
    dest.write_bytes(content)
    log_ingest_event(
        {
            "event": "fetch",
            "filename": CII_FILENAME,
            "url": f"{_FACTURX_SDIST_URL}#{_FACTURX_SDIST_MEMBER}",
            "bytes": len(content),
        }
    )
    print(f"fetched {CII_FILENAME} ({len(content)} bytes) <- factur-x sdist")


def _staging_dir() -> Path:
    d = STAGING_DIR / DOMAIN_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _corpus_dir() -> Path:
    d = CORPUS_DIR / DOMAIN_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def _save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def cmd_fetch(_: argparse.Namespace) -> None:
    dest_dir = _staging_dir()
    for filename, url in SOURCES:
        dest = dest_dir / filename
        response = httpx.get(url, headers=_HEADERS, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        dest.write_bytes(response.content)
        log_ingest_event(
            {"event": "fetch", "filename": filename, "url": url, "bytes": len(response.content)}
        )
        print(f"fetched {filename} ({len(response.content)} bytes) <- {url}")

    _fetch_cii_schema(dest_dir)


def cmd_promote(args: argparse.Namespace) -> None:
    staging = _staging_dir()
    corpus = _corpus_dir()
    manifest = _load_manifest()

    if args.all:
        targets = list(staging.glob("*"))
    else:
        targets = [staging / args.filename]

    known_urls = dict(SOURCES)
    known_urls[CII_FILENAME] = f"{_FACTURX_SDIST_URL}#{_FACTURX_SDIST_MEMBER}"

    for src in targets:
        if not src.is_file():
            print(f"skip (not a file): {src}", file=sys.stderr)
            continue
        digest = _sha256(src)
        dest = corpus / src.name
        shutil.copy2(src, dest)
        manifest[src.name] = {
            "source_url": known_urls.get(src.name, "unknown"),
            "sha256": digest,
            "promoted": True,
        }
        log_ingest_event({"event": "promote", "filename": src.name, "sha256": digest})
        print(f"promoted {src.name} (sha256 {digest[:12]}...)")

    _save_manifest(manifest)


def cmd_index(_: argparse.Namespace) -> None:
    from router.parsing import parse_document

    corpus = _corpus_dir()
    manifest = _load_manifest()

    total_chunks = 0
    for path in sorted(corpus.glob("*")):
        if not path.is_file():
            continue
        entry = manifest.get(path.name)
        if entry is None:
            print(f"skip {path.name}: not in manifest (promote it first)", file=sys.stderr)
            continue

        sections = parse_document(path)
        if not sections:
            print(f"skip {path.name}: parser produced no chunks", file=sys.stderr)
            continue

        ids, texts, metadatas = [], [], []
        for i, (section, text) in enumerate(sections):
            ids.append(f"{entry['sha256'][:16]}:{i}")
            texts.append(text)
            metadatas.append(
                {
                    "source_doc": path.name,
                    "sha256": entry["sha256"],
                    "section": section,
                }
            )

        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch_texts = texts[start : start + EMBED_BATCH_SIZE]
            batch_ids = ids[start : start + EMBED_BATCH_SIZE]
            batch_meta = metadatas[start : start + EMBED_BATCH_SIZE]
            vectors = embed(batch_texts)
            upsert_chunks(COLLECTION_NAME, batch_ids, vectors, batch_texts, batch_meta)

        total_chunks += len(texts)
        log_ingest_event({"event": "index", "filename": path.name, "chunks": len(texts)})
        print(f"indexed {path.name}: {len(texts)} chunks")

    print(f"done. {total_chunks} chunks indexed into collection {COLLECTION_NAME!r}.")


def cmd_status(_: argparse.Namespace) -> None:
    manifest = _load_manifest()
    staged = sorted(p.name for p in _staging_dir().glob("*") if p.is_file())
    promoted = sorted(manifest.keys())
    print("staged (untrusted):", staged or "(none)")
    print("promoted (trusted corpus):", promoted or "(none)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="router-ingest")
    sub = parser.add_subparsers(required=True)

    p_fetch = sub.add_parser("fetch", help="download public spec sources into staging")
    p_fetch.set_defaults(func=cmd_fetch)

    p_promote = sub.add_parser("promote", help="move a staged doc into the trusted corpus")
    p_promote.add_argument("filename", nargs="?", help="filename under the staging dir")
    p_promote.add_argument("--all", action="store_true", help="promote every staged file")
    p_promote.set_defaults(func=cmd_promote)

    p_index = sub.add_parser("index", help="chunk, embed, and upsert the promoted corpus")
    p_index.set_defaults(func=cmd_index)

    p_status = sub.add_parser("status", help="show staged vs promoted documents")
    p_status.set_defaults(func=cmd_status)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
