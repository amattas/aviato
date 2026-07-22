"""In-memory :class:`aviato.core.ports.Advisor` for testing Track L advisories (D3).

Advisories are provider-neutral behind the port; a core-level fake keeps the port exercised
and pins the test double to the protocol the real contained binding implements — with no
network, no cost, and deterministic output. ``fail=True`` simulates the model being
unavailable/over budget so a caller's fail-open-but-loud path can be tested.
"""

from __future__ import annotations

from collections.abc import Callable

from aviato.core.ports import AdviceRequest, AdviceResponse


class FakeAdvisor:
    def __init__(
        self,
        *,
        model: str = "fake-model",
        responder: Callable[[AdviceRequest], str] | None = None,
        fail: bool = False,
    ) -> None:
        self._model = model
        self._responder = responder
        self._fail = fail
        self.calls: list[AdviceRequest] = []

    @property
    def model(self) -> str:
        return self._model

    def advise(self, request: AdviceRequest) -> AdviceResponse:
        self.calls.append(request)
        if self._fail:
            raise RuntimeError("advisor unavailable")
        text = self._responder(request) if self._responder is not None else f"[{request.feature}] advice"
        return AdviceResponse(text=text, model=self._model)
