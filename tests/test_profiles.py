from __future__ import annotations

import pytest

from aviato.profiles import profile_plan


def test_swift_app_profile_declares_app_store_requirements() -> None:
    plan = profile_plan("swift-app")

    assert "templates/profile-swift-app.yml" in plan.templates
    assert "app-store-connect" in plan.environments
    assert "APP_STORE_CONNECT_KEY_ID" in plan.secrets


def test_unknown_profile_lists_available_profiles() -> None:
    with pytest.raises(ValueError, match="available profiles"):
        profile_plan("not-a-profile")
