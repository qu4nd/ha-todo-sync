"""Tests for release version calculation."""

import pytest

from scripts.release_version import calculate_release_version, parse_version


@pytest.mark.parametrize(
    ("bump", "expected"),
    [
        ("patch", "0.1.31"),
        ("minor", "0.2.0"),
        ("major", "1.0.0"),
    ],
)
def test_stable_release_bumps_current_stable_version(bump, expected):
    assert calculate_release_version("0.1.30", "stable", bump) == expected


def test_first_beta_uses_selected_next_stable_target():
    assert calculate_release_version("0.1.30", "beta", "patch") == "0.1.31b1"


def test_next_beta_increments_existing_beta_tag():
    assert (
        calculate_release_version(
            "0.1.31b1", "beta", "patch", ["v0.1.31b1"]
        )
        == "0.1.31b2"
    )


def test_beta_number_uses_highest_existing_tag_without_reuse():
    assert (
        calculate_release_version(
            "0.1.30",
            "beta",
            "patch",
            ["v0.1.31b1", "v0.1.31b3", "v0.1.30b9"],
        )
        == "0.1.31b4"
    )


def test_stable_release_finalizes_current_beta_target():
    assert (
        calculate_release_version(
            "0.1.31b2", "stable", "patch", ["v0.1.31b1", "v0.1.31b2"]
        )
        == "0.1.31"
    )


def test_unpublished_current_beta_blocks_next_beta():
    with pytest.raises(ValueError, match="not published yet"):
        calculate_release_version("0.1.31b1", "beta", "patch")


def test_beta_release_from_beta_manifest_keeps_same_target():
    assert (
        calculate_release_version(
            "0.1.31b1", "beta", "major", ["v0.1.31b1"]
        )
        == "0.1.31b2"
    )


def test_existing_stable_tag_blocks_duplicate_release():
    with pytest.raises(ValueError, match="already exists"):
        calculate_release_version(
            "0.1.30", "beta", "patch", ["v0.1.31"]
        )


@pytest.mark.parametrize("version", ["0.1", "v0.1.30", "0.1.30-rc1", "0.1.30b0"])
def test_parse_version_rejects_unsupported_formats(version):
    with pytest.raises(ValueError, match="Unsupported version"):
        parse_version(version)


def test_invalid_release_type_is_rejected():
    with pytest.raises(ValueError, match="Unsupported release type"):
        calculate_release_version("0.1.30", "nightly", "patch")


def test_invalid_bump_is_rejected_for_stable_manifest():
    with pytest.raises(ValueError, match="Unsupported version bump"):
        calculate_release_version("0.1.30", "beta", "invalid")
