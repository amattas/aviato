# mypy: ignore-errors
"""Disposable CodeQL blocking canary. Never merge this file."""

from flask import Flask, request  # type: ignore[import-not-found]

app = Flask(__name__)


@app.route("/codeql-canary")
def evaluate_untrusted_expression() -> object:
    """Deliberately pass an HTTP request parameter to a code-evaluation sink."""
    expression = request.args.get("expression")
    return eval(expression)  # noqa: B307
