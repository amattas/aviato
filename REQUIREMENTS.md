# Aviato — Requirements & Architecture

The requirements were split into per-module documents on 2026-07-11. Original
§ numbering is preserved verbatim in the split files, so citations like "§5.2"
in code docstrings remain valid.

- **§ index / entry point:** [docs/requirements/README.md](docs/requirements/README.md)
- Core principles & contracts: `docs/requirements/core/`
- Per-module process flows & plug-ins: `docs/requirements/modules/`

`tests/test_docs_index.py` guards that every § cited in `aviato/**/*.py`
resolves through the index.
