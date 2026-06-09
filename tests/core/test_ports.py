"""The in-memory test double must satisfy the §2.14 Platform port.

Core-flow tests run against FakePlatform; if its surface drifts from the protocol the
real binding implements, those tests would pass against a shape GitHubPlatform doesn't
have. The isinstance assert (Platform is @runtime_checkable) pins the two together.
"""

from aviato.core.ports import Platform

from .fakeplatform import FakePlatform


def test_fakeplatform_satisfies_platform_protocol() -> None:
    assert isinstance(FakePlatform(), Platform)
