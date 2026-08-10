#!/usr/bin/env python3
"""Fail closed on common secret patterns and forbidden public-release artifacts."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".yaml", ".yml", ".txt", ".sh", ".example", ""}
FORBIDDEN_NAMES = {".env", "pms.db", "patients.db"}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_server_path": re.compile(r"/root/(?:dts-dental|dental-ai-suite)"),
    "private_project_name": re.compile(r"\bdts-dental\b", re.IGNORECASE),
}
PHONE_PATTERN = re.compile(r"\b(?:\d{3}[-.) ]*){2}\d{4}\b")
RESERVED_PHONE = re.compile(r"^202-555-01\d{2}$")


def normalized_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}" if len(digits) == 10 else value


def main() -> int:
    findings: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        relative = path.relative_to(ROOT)
        if path.name in FORBIDDEN_NAMES:
            findings.append(f"forbidden artifact: {relative}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile", ".gitignore", ".dockerignore"}:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if relative == Path("scripts/secret_scan.py"):
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{name}: {relative}")
        if relative.parts[0] in {"practice_management_software", "voice_pipeline", "evals", "tests"}:
            for match in PHONE_PATTERN.finditer(text):
                phone = normalized_phone(match.group(0))
                if phone.startswith("202-555-") and not RESERVED_PHONE.fullmatch(phone):
                    findings.append(f"non-reserved synthetic phone: {relative}: {phone}")

    if findings:
        print("Public-release scan failed:")
        print("\n".join(f"- {finding}" for finding in findings))
        return 1
    print("Public-release scan passed: no forbidden artifacts or known secret patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
