from __future__ import annotations

from aviato.cli import main


def test_exit_zero_when_highest() -> None:
    assert main(["is-highest", "1.2.0", "1.0.0", "1.2.0"]) == 0


def test_exit_one_when_not_highest() -> None:
    assert main(["is-highest", "1.0.0", "1.2.0"]) == 1


def test_release_outranks_prerelease() -> None:
    assert main(["is-highest", "1.2.0", "1.2.0-beta2", "1.2.0"]) == 0
    assert main(["is-highest", "1.2.0-beta2", "1.2.0"]) == 1


def test_no_existing_tags_is_highest() -> None:
    assert main(["is-highest", "1.0.0"]) == 0
