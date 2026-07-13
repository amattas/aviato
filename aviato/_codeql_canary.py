"""Disposable CodeQL blocking canary. Never merge this file."""


def evaluate_untrusted_expression() -> object:
    """Deliberately pass untrusted input to a code-evaluation sink."""
    return eval(input("expression: "))
