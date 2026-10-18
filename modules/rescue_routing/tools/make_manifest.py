"""Integrity manifest generator computing sha256 checksums across critical engine files."""

import hashlib
from pathlib import Path


def compute_sha256(filepath: str | Path) -> str:
    """Compute hex SHA-256 digest of a file in binary mode."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest(manifest_path: str | Path = "MANIFEST.sha256") -> Path:
    """Compute sha256 checksums of code, schema, data, and deliverables, writing MANIFEST.sha256."""
    files_to_hash = []

    # Explicit deliverable, contract, doc, and test files
    critical_explicit = [
        "routes.json",
        "schema.json",
        "benchmark_results.json",
        "LIMITATIONS.md",
        "CHANGELOG_FOR_PERSON1.md",
        "FIELDS.md",
        "test_router.py",
    ]
    for f in critical_explicit:
        p = Path(f)
        if p.exists():
            files_to_hash.append(p)

    # data/*.json
    data_dir = Path("data")
    if data_dir.exists():
        for p in sorted(data_dir.glob("*.json")):
            files_to_hash.append(p)

    # modules/rescue_routing/*.py
    modules_dir = Path("modules/rescue_routing")
    if modules_dir.exists():
        for p in sorted(modules_dir.glob("*.py")):
            files_to_hash.append(p)

    lines = []
    for p in sorted(files_to_hash, key=lambda x: str(x).replace("\\", "/")):
        rel_path = str(p).replace("\\", "/")
        sha = compute_sha256(p)
        lines.append(f"{sha}  {rel_path}\n")

    out_file = Path(manifest_path)
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)

    return out_file


if __name__ == "__main__":
    out = generate_manifest()
    print(f"Generated integrity manifest at {out}")
