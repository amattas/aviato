# Aviato requirements and specifications

The requirements were split into per-module documents on 2026-07-11. Original
§ numbering is preserved verbatim in the split files, so citations like "§5.2"
in code docstrings remain valid.

- **§ index / entry point:** [docs/requirements/README.md](docs/requirements/README.md)
- Requirements (outcomes, constraints, acceptance): `docs/requirements/`
- Specifications (precise process and plug-in behavior): `docs/specifications/`
- Architecture (current structure): `docs/architecture/`

`tests/test_docs_index.py` guards that every § cited in `aviato/**/*.py`
resolves through the index, including behavioral sections now classified as
specifications.
