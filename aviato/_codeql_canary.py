# mypy: ignore-errors
"""Disposable CodeQL blocking canary. Never merge this file."""

from django.http import HttpRequest, HttpResponse  # type: ignore[import-not-found]


def evaluate_untrusted_expression(request: HttpRequest) -> HttpResponse:
    """Deliberately pass an HTTP request parameter to a code-evaluation sink."""
    expression = request.POST.get("expression", "")
    return HttpResponse(str(eval(expression)))  # noqa: B307
