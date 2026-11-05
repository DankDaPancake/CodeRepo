# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
"""Milestone 2 parser.

Stages, in the order the runner calls them for each version of each paper:

- ``gather``: multi-file gathering, the root ``.tex`` and the files it pulls in
- ``normalize``: cleanup of meaningless formatting, one spelling for inline and block math
- ``hierarchy`` (with ``sentences``): the tree of sections, sentences, formulas and figures
- ``bibitem``: ``\\bibitem``, ``.bib`` (and a kept ``.bbl``) -> BibTeX rows
- ``dedup``: one paper, all versions -> the rows of ``elements``, ``hierarchy`` and ``bibtex``
- ``writer``: the rows of a shard -> three Parquet files

``run`` is the runner (one command for the whole corpus, resumable, ``--workers``); the types
shared by the stages are in ``model`` and the interfaces in ``specs/0005-m2-runner.md``.
``sample_set`` builds a development sample of the crawled corpus.
"""
