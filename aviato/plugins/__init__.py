"""Day-zero plug-in tree.

Everything language- or deployment-specific lives here (or in the data trees
under ``profiles/`` and ``bundles/``), never in :mod:`aviato.core`. The core has
no import edge into this package (enforced by :mod:`aviato.core.selfcheck`).
"""
