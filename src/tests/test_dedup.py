# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
from src.parser.bibitem import BibEntry
from src.parser.dedup import dedup, merge_references, rename_citations
from src.parser.model import EMPTY, PARSED, Node, VersionParse


def tree(*children):
    return Node("document", "", list(children))


def sec(title, *children):
    return Node("section", title, list(children))


def sent(text):
    return Node("sentence", text)


def by_kind(rows, kind):
    return [r for r in rows["elements"] if r["kind"] == kind]


def edges(rows, version):
    return [(r["element_id"], r["parent_id"]) for r in rows["hierarchy"] if r["version"] == version]


def test_equal_sentences_of_two_versions_share_one_element_with_different_parents():
    v1 = VersionParse(1, PARSED, tree(sec("Intro", sent("Same.")), sec("Other", sent("Only v1."))))
    v2 = VersionParse(2, PARSED, tree(sec("Intro"), sec("Moved", sent("Same."))))
    rows = dedup("2310.12345", [v1, v2])
    sentences = {r["content"]: r["element_id"] for r in by_kind(rows, "sentence")}
    assert len(sentences) == 2 and all(i.startswith("2310-12345#s") for i in sentences.values())
    same = sentences["Same."]
    parents = {r["version"]: r["parent_id"] for r in rows["hierarchy"] if r["element_id"] == same}
    assert parents[1] != parents[2]  # shared element, one parent per version
    assert len([r for r in rows["elements"] if r["content"] == "Same."]) == 1
    intro = {r["element_id"] for r in by_kind(rows, "section") if r["content"] == "Intro"}
    assert len(intro) == 1  # the section is shared too: same title, same parent


def test_a_version_without_tex_is_kept_as_a_root_only():
    rows = dedup("2310.12345", [VersionParse(1, PARSED, tree(sent("A."))), VersionParse(2, EMPTY)])
    assert edges(rows, 2) == [("2310-12345#root2", "2310-12345")]
    assert len(by_kind(rows, "document")) == 2


def test_hierarchy_ids_are_the_paper_key_plus_a_discriminant():
    rows = dedup("hep-th/9901001", [VersionParse(1, PARSED, tree(sent("A.")))])
    assert all(r["element_id"].startswith("hep-th/9901001#") for r in rows["elements"])


def test_same_title_under_the_same_parent_twice_gives_two_elements():
    t = tree(sec("Proof", sent("One.")), sec("Proof", sent("Two.")))
    rows = dedup("2310.00001", [VersionParse(1, PARSED, t)])
    proofs = [r["element_id"] for r in by_kind(rows, "section")]
    assert len(proofs) == 2 and len(set(proofs)) == 2
    children = {
        r["parent_id"] for r in rows["hierarchy"] if r["element_id"].endswith(("#s1", "#s2"))
    }
    assert children == set(proofs)  # each sentence hangs from its own "Proof"


def test_repeated_identical_edge_in_one_version_is_written_once():
    rows = dedup("2310.00001", [VersionParse(1, PARSED, tree(sent("Hi."), sent("Hi.")))])
    assert len(rows["hierarchy"]) == 2  # root + one sentence edge


def test_branch_with_equal_title_in_different_parents_is_not_merged():
    t = tree(sec("A", sec("Proof", sent("p."))), sec("B", sec("Proof", sent("q."))))
    rows = dedup("2310.00001", [VersionParse(1, PARSED, t)])
    assert len([r for r in by_kind(rows, "section") if r["content"] == "Proof"]) == 2


def entry(key, title, **kw):
    return BibEntry(citation_key=key, title=title, **kw)


def test_the_same_reference_under_two_keys_becomes_one_and_citations_follow():
    v1 = VersionParse(
        1,
        PARSED,
        tree(sent(r"Attention \cite{vaswani2017} works."), sent(r"Also \citep{vaswani2017,x}.")),
        [
            entry("vaswani2017", "Attention is all you need", authors=["Ashish Vaswani"]),
            entry("x", "Another paper entirely different", doi="10.1/abc"),
        ],
    )
    v2 = VersionParse(
        2,
        PARSED,
        tree(sent(r"Attention \cite{vit_transformer} works.")),
        [
            entry("vit_transformer", "Attention is all you need", year=2017, doi="10.5555/3295222"),
        ],
    )
    rows = dedup("2310.12345", [v1, v2])
    keys = {r["citation_key"]: r for r in rows["bibtex"]}
    assert set(keys) == {"vaswani2017", "x"}  # one entry per reference
    merged = keys["vaswani2017"]
    assert merged["year"] == 2017 and merged["doi"] == "10.5555/3295222"
    assert merged["authors"] == ["Ashish Vaswani"]  # fields are united, none lost
    contents = {r["content"] for r in by_kind(rows, "sentence")}
    assert r"Attention \cite{vaswani2017} works." in contents
    assert r"Attention \cite{vit_transformer} works." not in contents
    # after renaming, the sentence of v1 and v2 is the same element
    ids = [r["element_id"] for r in rows["hierarchy"] if r["element_id"].endswith("#s1")]
    assert sorted(r["version"] for r in rows["hierarchy"] if r["element_id"] in ids) == [1, 2]


def test_two_different_references_with_the_same_key_are_kept_apart():
    v1 = VersionParse(
        1, PARSED, tree(sent(r"See \cite{ref1}.")), [entry("ref1", "First long title of paper")]
    )
    v2 = VersionParse(
        2, PARSED, tree(sent(r"See \cite{ref1}.")), [entry("ref1", "A completely other paper")]
    )
    rows = dedup("2310.12345", [v1, v2])
    assert sorted(r["citation_key"] for r in rows["bibtex"]) == ["ref1", "ref1_2"]
    contents = {r["content"] for r in by_kind(rows, "sentence")}
    assert contents == {r"See \cite{ref1}.", r"See \cite{ref1_2}."}


def test_a_duplicate_inside_one_version_is_merged_and_cite_lists_are_deduplicated():
    v = VersionParse(
        1,
        PARSED,
        tree(sent(r"Both \cite{a,b} agree.")),
        [
            entry("a", "Same paper title here, long", doi="10.1/x"),
            entry("b", "Same paper title here, long"),
        ],
    )
    rows = dedup("2310.12345", [v])
    assert [r["citation_key"] for r in rows["bibtex"]] == ["a"]
    assert [r["content"] for r in by_kind(rows, "sentence")] == [r"Both \cite{a} agree."]


def test_matching_by_arxiv_id_and_by_doi():
    a = BibEntry(
        "p", title=None, url="https://arxiv.org/abs/2001.01234", raw="Foo. arXiv:2001.01234"
    )
    b = BibEntry(
        "q",
        title="Some Title Which Is Long Enough",
        raw="Bar",
        journal="arXiv preprint arXiv:2001.01234",
    )
    c = BibEntry("r", title="Other", doi="10.1000/XYZ")
    d = BibEntry("s", title="Another title", doi="https://doi.org/10.1000/xyz")
    entries, renames = merge_references(
        [VersionParse(1, PARSED, None, [a, c]), VersionParse(2, PARSED, None, [b, d])]
    )
    assert len(entries) == 2
    assert renames[1]["p"] == renames[2]["q"] and renames[1]["r"] == renames[2]["s"]


def test_key_used_in_most_versions_wins():
    same = "A reasonably long reference title"
    versions = [
        VersionParse(1, PARSED, None, [entry("old", same)]),
        VersionParse(2, PARSED, None, [entry("new", same)]),
        VersionParse(3, PARSED, None, [entry("new", same)]),
    ]
    entries, _ = merge_references(versions)
    assert [e.citation_key for e in entries] == ["new"]


def test_rename_citations_handles_options_and_unknown_keys():
    out = rename_citations(r"\citep[see][p.~3]{a,b,zz} and \nocite{a}", {"a": "A", "b": "A"})
    assert out == r"\citep[see][p.~3]{A,zz} and \nocite{A}"
    assert rename_citations("no citations", {"a": "A"}) == "no citations"


def test_rows_are_plain_dicts_with_the_statement_columns():
    rows = dedup("2310.12345", [VersionParse(1, PARSED, tree(sent("A.")), [entry("k", "T")])])
    assert set(rows) == {"elements", "hierarchy", "bibtex"}
    assert set(rows["elements"][0]) == {"element_id", "arxiv_id", "kind", "content"}
    assert set(rows["hierarchy"][0]) == {"arxiv_id", "version", "element_id", "parent_id"}
    assert set(rows["bibtex"][0]) == {
        "arxiv_id",
        "citation_key",
        "entry_type",
        "title",
        "authors",
        "year",
        "doi",
        "journal",
        "url",
    }
