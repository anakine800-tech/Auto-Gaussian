#!/usr/bin/env python3
"""Build, validate, and finalize Auto-G16 release provenance manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA = "auto-g16-release-provenance/1"
PROJECT = "Auto-G16"
REPOSITORY_URL = "https://github.com/anakine800-tech/Auto-Gaussian"
SIGNATURE_REQUIRED_AFTER = (2, 3, 0)
HEX_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
DOI = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
REVISION_SWHID = re.compile(r"^swh:1:rev:([0-9a-f]{40})(?:;\S+)?$")
SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
SIGNATURE_MARKERS = {
    "ssh": "-----BEGIN SSH SIGNATURE-----",
    "openpgp": "-----BEGIN PGP SIGNATURE-----",
}
README_MARKERS = {
    "version_doi": (
        "<!-- release-provenance:version-doi:start -->",
        "<!-- release-provenance:version-doi:end -->",
    ),
    "concept_doi": (
        "<!-- release-provenance:concept-doi:start -->",
        "<!-- release-provenance:concept-doi:end -->",
    ),
    "swhid": (
        "<!-- release-provenance:swhid:start -->",
        "<!-- release-provenance:swhid:end -->",
    ),
}


class ProvenanceError(ValueError):
    """Controlled release-provenance validation failure."""


def _reject_constant(value: str) -> None:
    raise ProvenanceError(f"non-finite JSON number is forbidden: {value}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProvenanceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProvenanceError("manifest root must be an object")
    return value


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_file(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or ".." in posix.parts:
        raise ProvenanceError(f"path must be a normalized repository-relative path: {relative}")
    if str(posix) != relative or "\\" in relative:
        raise ProvenanceError(f"path is not canonical POSIX form: {relative}")
    candidate = root.joinpath(*posix.parts)
    current = root
    for part in posix.parts:
        current = current / part
        if current.is_symlink():
            raise ProvenanceError(f"symlinked release evidence is forbidden: {relative}")
    if not candidate.is_file():
        raise ProvenanceError(f"release evidence file does not exist: {relative}")
    return candidate


def parse_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise ProvenanceError(f"invalid semantic version: {value}")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def parse_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvenanceError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ProvenanceError("release timestamp must include a timezone")


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise ProvenanceError(f"git {' '.join(args)} failed: {message}")
    return result.stdout.strip()


def inspect_tag(root: Path, tag: str) -> dict[str, Any]:
    if run_git(root, "cat-file", "-t", tag) != "tag":
        raise ProvenanceError(f"release tag must be annotated: {tag}")
    tag_text = run_git(root, "cat-file", "-p", tag)
    signature_type = next(
        (name for name, marker in SIGNATURE_MARKERS.items() if marker in tag_text), None
    )
    version = tag.removeprefix("v")
    signature_required = parse_semver(version) > SIGNATURE_REQUIRED_AFTER
    if signature_required and signature_type is None:
        raise ProvenanceError(
            f"release tags after v2.3.0 must carry an SSH or OpenPGP signature: {tag}"
        )
    return {
        "annotated": True,
        "commit_sha": run_git(root, "rev-parse", f"{tag}^{{commit}}"),
        "signature": {
            "format": signature_type,
            "present": signature_type is not None,
            "required": signature_required,
        },
        "tag_object_id": run_git(root, "rev-parse", tag),
    }


def file_binding(root: Path, relative: str) -> dict[str, Any]:
    path = safe_relative_file(root, relative)
    return {
        "bytes": path.stat().st_size,
        "path": relative,
        "sha256": sha256_file(path),
    }


def make_manifest(
    root: Path,
    *,
    tag: str,
    published_at: str,
    release_url: str,
    citation_path: str,
    artifacts: Iterable[str],
    version_doi: str | None,
    concept_doi: str | None,
    swhid: str | None,
) -> dict[str, Any]:
    if not tag.startswith("v"):
        raise ProvenanceError("release tag must begin with v")
    version = tag[1:]
    parse_semver(version)
    parse_timestamp(published_at)
    expected_url = f"{REPOSITORY_URL}/releases/tag/{tag}"
    if release_url != expected_url:
        raise ProvenanceError(f"release URL must be {expected_url}")
    source = inspect_tag(root, tag)
    manifest = {
        "artifacts": [file_binding(root, path) for path in artifacts],
        "citation": file_binding(root, citation_path),
        "identifiers": {
            "concept_doi": concept_doi,
            "software_heritage_swhid": swhid,
            "version_doi": version_doi,
        },
        "manifest_status": (
            "post_release_backfill"
            if parse_semver(version) <= SIGNATURE_REQUIRED_AFTER
            else "release_native"
        ),
        "project": PROJECT,
        "published_at": published_at,
        "release_url": release_url,
        "repository_url": REPOSITORY_URL,
        "schema": SCHEMA,
        "source": source,
        "tag": tag,
        "version": version,
    }
    validate_manifest(root, manifest, check_git=True)
    return manifest


def _require_exact_keys(value: dict[str, Any], expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ProvenanceError(
            f"{where} keys differ; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _validate_binding(root: Path, value: Any, where: str) -> None:
    if not isinstance(value, dict):
        raise ProvenanceError(f"{where} must be an object")
    _require_exact_keys(value, {"bytes", "path", "sha256"}, where)
    if isinstance(value["bytes"], bool) or not isinstance(value["bytes"], int):
        raise ProvenanceError(f"{where}.bytes must be an integer")
    if value["bytes"] < 0:
        raise ProvenanceError(f"{where}.bytes cannot be negative")
    if not isinstance(value["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["sha256"]
    ):
        raise ProvenanceError(f"{where}.sha256 must be lowercase SHA-256")
    if not isinstance(value["path"], str):
        raise ProvenanceError(f"{where}.path must be a string")
    path = safe_relative_file(root, value["path"])
    if path.stat().st_size != value["bytes"]:
        raise ProvenanceError(f"{where} byte size drift")
    if sha256_file(path) != value["sha256"]:
        raise ProvenanceError(f"{where} SHA-256 drift")


def validate_manifest(
    root: Path, manifest: dict[str, Any], *, check_git: bool | None = None
) -> None:
    _require_exact_keys(
        manifest,
        {
            "artifacts",
            "citation",
            "identifiers",
            "manifest_status",
            "project",
            "published_at",
            "release_url",
            "repository_url",
            "schema",
            "source",
            "tag",
            "version",
        },
        "manifest",
    )
    if manifest["schema"] != SCHEMA or manifest["project"] != PROJECT:
        raise ProvenanceError("unexpected release manifest schema or project")
    if manifest["repository_url"] != REPOSITORY_URL:
        raise ProvenanceError("repository URL drift")
    if not isinstance(manifest["version"], str):
        raise ProvenanceError("version must be a string")
    version_tuple = parse_semver(manifest["version"])
    expected_status = (
        "post_release_backfill"
        if version_tuple <= SIGNATURE_REQUIRED_AFTER
        else "release_native"
    )
    if manifest["manifest_status"] != expected_status:
        raise ProvenanceError("release manifest status and version disagree")
    if manifest["tag"] != f"v{manifest['version']}":
        raise ProvenanceError("tag and version disagree")
    parse_timestamp(manifest["published_at"])
    if manifest["release_url"] != (
        f"{REPOSITORY_URL}/releases/tag/{manifest['tag']}"
    ):
        raise ProvenanceError("release URL and tag disagree")

    source = manifest["source"]
    if not isinstance(source, dict):
        raise ProvenanceError("source must be an object")
    _require_exact_keys(
        source, {"annotated", "commit_sha", "signature", "tag_object_id"}, "source"
    )
    if source["annotated"] is not True:
        raise ProvenanceError("release tag must be annotated")
    for field in ("commit_sha", "tag_object_id"):
        if not isinstance(source[field], str) or not HEX_OBJECT_ID.fullmatch(source[field]):
            raise ProvenanceError(f"source.{field} is not a Git object ID")
    signature = source["signature"]
    if not isinstance(signature, dict):
        raise ProvenanceError("source.signature must be an object")
    _require_exact_keys(signature, {"format", "present", "required"}, "source.signature")
    expected_required = version_tuple > SIGNATURE_REQUIRED_AFTER
    if signature["required"] is not expected_required:
        raise ProvenanceError("tag signature policy classification drift")
    if not isinstance(signature["present"], bool):
        raise ProvenanceError("signature.present must be boolean")
    if signature["format"] not in (None, "ssh", "openpgp"):
        raise ProvenanceError("unsupported tag signature format")
    if signature["present"] != (signature["format"] is not None):
        raise ProvenanceError("signature presence and format disagree")
    if expected_required and not signature["present"]:
        raise ProvenanceError("future release is missing its required tag signature")

    _validate_binding(root, manifest["citation"], "citation")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list):
        raise ProvenanceError("artifacts must be an array")
    seen_paths: set[str] = set()
    for index, artifact in enumerate(artifacts):
        _validate_binding(root, artifact, f"artifacts[{index}]")
        path = artifact["path"]
        if path in seen_paths:
            raise ProvenanceError(f"duplicate artifact path: {path}")
        seen_paths.add(path)

    identifiers = manifest["identifiers"]
    if not isinstance(identifiers, dict):
        raise ProvenanceError("identifiers must be an object")
    _require_exact_keys(
        identifiers,
        {"concept_doi", "software_heritage_swhid", "version_doi"},
        "identifiers",
    )
    for field in ("version_doi", "concept_doi"):
        value = identifiers[field]
        if value is not None and (not isinstance(value, str) or not DOI.fullmatch(value)):
            raise ProvenanceError(f"identifiers.{field} is not a DOI")
    if (
        identifiers["version_doi"] is not None
        and identifiers["version_doi"] == identifiers["concept_doi"]
    ):
        raise ProvenanceError("version DOI and concept DOI must differ")
    swhid = identifiers["software_heritage_swhid"]
    if swhid is not None:
        if not isinstance(swhid, str):
            raise ProvenanceError("identifiers.software_heritage_swhid is invalid")
        swhid_match = REVISION_SWHID.fullmatch(swhid)
        if not swhid_match:
            raise ProvenanceError("release SWHID must identify a Software Heritage revision")
        if swhid_match.group(1) != source["commit_sha"]:
            raise ProvenanceError("release SWHID revision and Git commit SHA disagree")

    if check_git is None:
        check_git = (root / ".git").exists()
    if check_git:
        observed = inspect_tag(root, manifest["tag"])
        if observed != source:
            raise ProvenanceError("manifest source binding differs from the Git tag")

    for item in _walk_numbers(manifest):
        if isinstance(item, float) and not math.isfinite(item):
            raise ProvenanceError("non-finite manifest number")


def _walk_numbers(value: Any) -> Iterable[int | float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_numbers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_numbers(child)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def replace_readme_marker(text: str, field: str, value: str) -> str:
    start, end = README_MARKERS[field]
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    replacement = f"{start}`{value}`{end}"
    updated, count = pattern.subn(replacement, text)
    if count != 1:
        raise ProvenanceError(f"README must contain exactly one marker pair for {field}")
    return updated


def update_identifiers(
    root: Path,
    manifest_path: Path,
    *,
    version_doi: str | None,
    concept_doi: str | None,
    swhid: str | None,
    readme_path: Path | None,
) -> None:
    if not any((version_doi, concept_doi, swhid)):
        raise ProvenanceError("at least one DOI or SWHID must be supplied")
    if (version_doi is None) != (concept_doi is None):
        raise ProvenanceError("version DOI and concept DOI must be supplied together")
    manifest = load_json(manifest_path)
    validate_manifest(root, manifest)
    requested = {
        "version_doi": version_doi,
        "concept_doi": concept_doi,
        "software_heritage_swhid": swhid,
    }
    for field, value in requested.items():
        if value is None:
            continue
        existing = manifest["identifiers"][field]
        if existing not in (None, value):
            raise ProvenanceError(f"refusing to replace existing {field}: {existing}")
        manifest["identifiers"][field] = value
    validate_manifest(root, manifest)
    updated_readme: str | None = None
    if readme_path is not None:
        text = readme_path.read_text(encoding="utf-8")
        if version_doi is not None:
            text = replace_readme_marker(text, "version_doi", version_doi)
        if concept_doi is not None:
            text = replace_readme_marker(text, "concept_doi", concept_doi)
        if swhid is not None:
            text = replace_readme_marker(text, "swhid", swhid)
        updated_readme = text

    atomic_write(manifest_path, canonical_json(manifest))
    if readme_path is not None and updated_readme is not None:
        atomic_write(readme_path, updated_readme)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="generate one new manifest")
    generate.add_argument("--tag", required=True)
    generate.add_argument("--published-at", required=True)
    generate.add_argument("--release-url", required=True)
    generate.add_argument(
        "--citation",
        help=(
            "immutable versioned CFF snapshot; defaults to "
            "release-manifests/citations/<tag>.cff"
        ),
    )
    generate.add_argument("--artifact", action="append", default=[])
    generate.add_argument("--version-doi")
    generate.add_argument("--concept-doi")
    generate.add_argument("--swhid")
    generate.add_argument("--output", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="validate an existing manifest")
    validate.add_argument("--manifest", type=Path, required=True)

    update = subparsers.add_parser(
        "update-identifiers", help="fill previously empty DOI/SWHID fields"
    )
    update.add_argument("--manifest", type=Path, required=True)
    update.add_argument("--version-doi")
    update.add_argument("--concept-doi")
    update.add_argument("--swhid")
    update.add_argument("--readme", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repo.resolve()
    try:
        if args.command == "generate":
            output = args.output if args.output.is_absolute() else root / args.output
            if output.exists():
                raise ProvenanceError(f"refusing to overwrite existing manifest: {output}")
            citation = args.citation or f"release-manifests/citations/{args.tag}.cff"
            manifest = make_manifest(
                root,
                tag=args.tag,
                published_at=args.published_at,
                release_url=args.release_url,
                citation_path=citation,
                artifacts=args.artifact,
                version_doi=args.version_doi,
                concept_doi=args.concept_doi,
                swhid=args.swhid,
            )
            atomic_write(output, canonical_json(manifest))
        elif args.command == "validate":
            path = args.manifest if args.manifest.is_absolute() else root / args.manifest
            validate_manifest(root, load_json(path))
        elif args.command == "update-identifiers":
            path = args.manifest if args.manifest.is_absolute() else root / args.manifest
            readme = None
            if args.readme is not None:
                readme = args.readme if args.readme.is_absolute() else root / args.readme
            update_identifiers(
                root,
                path,
                version_doi=args.version_doi,
                concept_doi=args.concept_doi,
                swhid=args.swhid,
                readme_path=readme,
            )
    except ProvenanceError as exc:
        print(f"release provenance error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
