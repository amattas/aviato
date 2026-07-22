"""The in-memory test doubles must satisfy the core §2.14/D3 ports.

Core-flow tests run against these fakes; if a fake's surface drifts from the protocol the
real binding implements, those tests would pass against a shape the real binding doesn't
have. The isinstance asserts (both ports are @runtime_checkable) pin them together.
"""

from aviato.core.ports import Advisor, Platform

from .fakeadvisor import FakeAdvisor
from .fakeplatform import FakePlatform


def test_fakeplatform_satisfies_platform_protocol() -> None:
    assert isinstance(FakePlatform(), Platform)


def test_fakeadvisor_satisfies_advisor_protocol() -> None:
    assert isinstance(FakeAdvisor(), Advisor)
