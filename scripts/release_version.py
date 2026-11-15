"""Calculate release versions for the manual GitHub Actions release workflow."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:b(?P<beta>[1-9][0-9]*))?$"
)
MANIFEST_PATH = Path("custom_components/todo_sync/manifest.json")


def parse_version(version: str) -> tuple[int, int, int, int | None]:
    """Parse a stable or beta version without accepting ambiguous formats."""
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"Unsupported version: {version}")

    major, minor, patch = (
        int(match.group(name)) for name in ("major", "minor", "patch")
    )
    beta = int(match.group("beta")) if match.group("beta") else None
    return major, minor, patch, beta


def format_version(
    major: int, minor: int, patch: int, beta: int | None = None
) -> str:
    """Format a version using the Home Assistant-compatible bN suffix."""
    stable = f"{major}.{minor}.{patch}"
    return f"{stable}b{beta}" if beta is not None else stable


def calculate_release_version(
    current_version: str,
    release_type: str,
    bump: str,
    existing_tags: Iterable[str] = (),
) -> str:
    """Calculate the next stable or beta version without reusing a tag.

    A beta series starts from the selected bump when the manifest is stable.
    Further betas reuse that target and increment the highest existing beta
    number. A stable release from a beta manifest finalizes the same target.
    """
    major, minor, patch, current_beta = parse_version(current_version)
    tags = set(existing_tags)

    if release_type not in {"stable", "beta"}:
        raise ValueError(f"Unsupported release type: {release_type}")

    if current_beta is None:
        if bump == "major":
            major, minor, patch = major + 1, 0, 0
        elif bump == "minor":
            minor, patch = minor + 1, 0
        elif bump == "patch":
            patch += 1
        else:
            raise ValueError(f"Unsupported version bump: {bump}")

    stable_version = format_version(major, minor, patch)
    stable_tag = f"v{stable_version}"

    if stable_tag in tags:
        raise ValueError(f"Stable release {stable_tag} already exists")

    if release_type == "stable":
        return stable_version

    current_beta_tag = (
        f"v{format_version(major, minor, patch, current_beta)}"
        if current_beta is not None
        else None
    )
    if current_beta_tag is not None and current_beta_tag not in tags:
        raise ValueError(
            f"Current beta release {current_beta_tag} is not published yet; "
            "publish it before preparing another beta"
        )

    beta_numbers = [current_beta] if current_beta is not None else []
    beta_tag_pattern = re.compile(
        rf"^v{re.escape(stable_version)}b([1-9][0-9]*)$"
    )
    for tag in tags:
        match = beta_tag_pattern.fullmatch(tag)
        if match:
            beta_numbers.append(int(match.group(1)))

    return format_version(major, minor, patch, max(beta_numbers, default=0) + 1)


def main() -> None:
    """Update manifest.json and expose the selected version to GitHub Actions."""
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    current_version = manifest.get("version")
    if not isinstance(current_version, str):
        raise SystemExit("manifest.json must contain a string version")

    existing_tags = subprocess.run(
        ["git", "tag", "--list"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    try:
        version = calculate_release_version(
            current_version,
            os.environ["RELEASE_TYPE"],
            os.environ["BUMP"],
            existing_tags,
        )
    except (KeyError, ValueError) as error:
        raise SystemExit(str(error)) from error

    # Keep the existing manifest formatting and key order intact.
    updated_text = re.sub(
        r'(?m)^([ \t]*"version"[ \t]*:[ \t]*")[^"]+(")',
        rf"\g<1>{version}\g<2>",
        manifest_text,
        count=1,
    )
    if updated_text == manifest_text:
        raise SystemExit("Could not update the version field in manifest.json")

    json.loads(updated_text)
    MANIFEST_PATH.write_text(updated_text, encoding="utf-8")

    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"new_version={version}\n")

    print(f"Prepared {'beta' if 'b' in version else 'stable'} version {version}")


if __name__ == "__main__":
    main()
