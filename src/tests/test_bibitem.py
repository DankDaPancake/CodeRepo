# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
import random
import string

import pytest

from src.parser.bibitem import (
    BibEntry,
    cite_keys,
    extract_references,
    find_year,
    main,
    parse_authors,
    parse_bib,
    parse_bibitems,
)
from src.parser.gather import TexVersion, gather


def one(text: str) -> BibEntry:
    entries = parse_bibitems(text)
    assert len(entries) == 1
    return entries[0]


# ------------------------------------------------------------------ \bibitem styles


def test_bibtex_plain_style_with_newblocks():
    e = one(
        "\\bibitem{vaswani2017}\n"
        "A.~Vaswani, N.~Shazeer, A.~N. Gomez, and I.~Polosukhin.\n"
        "\\newblock Attention is all you need.\n"
        "\\newblock In {\\em Advances in Neural Information Processing Systems}, "
        "pages 5998--6008, 2017.\n"
    )
    assert e.citation_key == "vaswani2017"
    assert e.authors == ["A. Vaswani", "N. Shazeer", "A. N. Gomez", "I. Polosukhin"]
    assert e.title == "Attention is all you need"
    assert e.journal == "Advances in Neural Information Processing Systems"
    assert e.year == 2017  # not 5998 or 6008
    assert e.entry_type == "inproceedings"


def test_natbib_label_gives_the_year_and_braces_are_removed_from_the_title():
    e = one(
        "\\bibitem[Devlin et~al.(2019)Devlin, Chang, Lee, and Toutanova]{devlin2019bert}\n"
        "Jacob Devlin, Ming-Wei Chang, Kenton Lee, and Kristina Toutanova.\n"
        "\\newblock {BERT}: Pre-training of deep bidirectional transformers.\n"
        "\\newblock In \\emph{Proceedings of NAACL-HLT}, pages 4171--4186, 2019.\n"
    )
    assert e.authors == ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"]
    assert e.title == "BERT: Pre-training of deep bidirectional transformers"
    assert (e.year, e.journal) == (2019, "Proceedings of NAACL-HLT")


def test_apalike_surname_first_with_year_after_the_authors():
    e = one(
        "\\bibitem[Kingma and Ba, 2015]{kingma2015adam}\n"
        "Kingma, D.~P. and Ba, J. (2015).\n"
        "\\newblock Adam: A method for stochastic optimization.\n"
        "\\newblock In {\\em ICLR}.\n"
    )
    assert e.authors == ["D. P. Kingma", "J. Ba"]
    assert (e.title, e.year, e.journal) == (
        "Adam: A method for stochastic optimization",
        2015,
        "ICLR",
    )


def test_ieee_quoted_title():
    e = one(
        "\\bibitem{he2016} K.~He, X.~Zhang, S.~Ren, and J.~Sun, ``Deep residual learning for "
        "image recognition,'' in \\emph{Proc. CVPR}, 2016, pp. 770--778."
    )
    assert e.authors == ["K. He", "X. Zhang", "S. Ren", "J. Sun"]
    assert e.title == "Deep residual learning for image recognition"
    assert (e.year, e.journal, e.entry_type) == (2016, "Proc. CVPR", "inproceedings")


def test_lncs_style_surname_initials_colon_title():
    e = one(
        "\\bibitem{ref1} Vaswani, A., Shazeer, N.: Attention is all you need. In: Advances in "
        "Neural Information Processing Systems. pp. 5998--6008 (2017)"
    )
    assert e.authors == ["A. Vaswani", "N. Shazeer"]
    assert e.title == "Attention is all you need"
    assert (e.year, e.journal) == (2017, "Advances in Neural Information Processing Systems")


def test_elsevier_style_comma_separated():
    e = one(
        "\\bibitem{b1} A. Vaswani, N. Shazeer, Attention is all you need, in: Advances in "
        "Neural Information Processing Systems, 2017, pp. 5998--6008."
    )
    assert e.authors == ["A. Vaswani", "N. Shazeer"]
    assert e.title == "Attention is all you need"
    assert e.year == 2017


def test_ams_style_italic_title_after_the_authors_then_journal():
    """Seen in the 100-paper smoke corpus (2606.25799, 2606.25737)."""
    e = one(
        "\\bibitem{Opial} Z. Opial, \\textit{Weak convergence of the sequence of successive "
        "approximations for nonexpansive mappings}, Bull. Amer. Math. Soc. \\textbf{73} (1967), "
        "591--597."
    )
    assert e.authors == ["Z. Opial"] and e.year == 1967
    assert e.title.startswith("Weak convergence") and e.title.endswith("mappings")
    assert (e.entry_type, e.journal) == ("article", "Bull. Amer. Math. Soc.")
    e = one(
        "\\bibitem{ms} B. Mazur and P. Swinnerton-Dyer, \\emph{Arithmetic of Weil Curves}, "
        "Invent. math. 25, 1--61, 1974."
    )
    assert (e.title, e.entry_type, e.journal) == (
        "Arithmetic of Weil Curves",
        "article",
        "Invent. math",
    )
    e = one(
        "\\bibitem{c} J. Doe and K. Roe, \\emph{On the thing}, in Proc. of the Big Conference, "
        "2001."
    )
    assert (e.title, e.entry_type) == ("On the thing", "inproceedings")


def test_hand_written_serial_comma_keeps_the_last_author():
    """Seen in the smoke corpus (2606.25824): ``A, B, and C, Title, Journal vol, pages (year)``."""
    e = one(
        "\\bibitem{r} R.~Rammal, G.~Toulouse, and M.~A.~Virasoro, Ultrametricity for physicists, "
        "Rev. Mod. Phys. 58 (3), 765--788 (1986)."
    )
    assert e.authors == ["R. Rammal", "G. Toulouse", "M. A. Virasoro"]
    assert e.title == "Ultrametricity for physicists" and e.year == 1986


def test_smoke_corpus_oddities_edition_publisher_et_al_and_thin_spaces():
    e = one(
        "\\bibitem{lm} Lind, D. and Marcus, B. \\textit{An Introduction to Symbolic Dynamics}, "
        "2nd Ed., Cambridge University Press (1995)."
    )
    assert (
        e.authors == ["D. Lind", "B. Marcus"] and e.title == "An Introduction to Symbolic Dynamics"
    )
    e = one(
        "\\bibitem{b} L.~D.~Barron, \\textit{Molecular Light Scattering and Optical Activity} "
        "(Cambridge University Press, 2004)."
    )
    assert e.authors == ["L. D. Barron"] and e.title.endswith("Optical Activity")
    e = one(
        "\\bibitem{y} Yu, Z., et al.: Don't Listen To Me: Understanding Jailbreak Prompts. "
        "In: USENIX Security Symposium (2024)"
    )
    assert e.authors == ["Z. Yu"] and e.title.startswith("Don't Listen To Me")
    e = one(
        "\\bibitem{c} N.\\,I.\\;Chkhalo, New concept for lithography, \\textit{Russ. J.}, 2020."
    )
    assert e.authors == ["N. I. Chkhalo"]


def test_arxiv_id_removal_keeps_the_commas_after_initials():
    """Seen in the smoke corpus (2606.25782): every ``Y.,`` lost its comma when an ID was cut."""
    e = one(
        "\\bibitem{d} Deng, Y., Zhang, W., Chen, Z., Gu, Q.: Rephrase and Respond: Let Large "
        "Language Models Ask Better Questions. arXiv preprint arXiv:2311.04205 (2023)"
    )
    assert e.authors == ["Y. Deng", "W. Zhang", "Z. Chen", "Q. Gu"]
    assert e.title.startswith("Rephrase and Respond") and e.year == 2023


def test_italic_journal_followed_by_the_volume_is_not_a_title():
    e = one("\\bibitem{n} J. Doe, \\emph{Nature} 12 (2000), 1--3.")
    assert e.journal == "Nature" and e.year == 2000


def test_hand_written_book_with_url_has_no_journal():
    e = one(
        "\\bibitem{dl} Ian Goodfellow, Yoshua Bengio, and Aaron Courville. Deep Learning. "
        "MIT Press, 2016. \\url{http://www.deeplearningbook.org}"
    )
    assert e.authors == ["Ian Goodfellow", "Yoshua Bengio", "Aaron Courville"]
    assert (e.title, e.year, e.entry_type) == ("Deep Learning", 2016, "book")
    assert e.url == "http://www.deeplearningbook.org" and e.journal is None


def test_arxiv_preprint_gets_an_abs_url_and_the_id_is_not_a_year():
    e = one(
        "\\bibitem{gpt3} Tom Brown et al. Language models are few-shot learners. "
        "arXiv preprint arXiv:2007.14165, 2020."
    )
    assert e.authors == ["Tom Brown"]  # "et al." is dropped
    assert e.title == "Language models are few-shot learners"
    assert e.year == 2020  # not 2007
    assert e.url == "https://arxiv.org/abs/2007.14165"
    assert e.journal == "arXiv preprint arXiv:2007.14165"


def test_acm_style_year_after_the_authors_and_doi():
    e = one(
        "\\bibitem{lecun} Yann LeCun, L{\\'e}on Bottou, and Yoshua Bengio. 1998. "
        "Gradient-based learning applied to document recognition. \\emph{Proc. IEEE}, "
        "86(11):2278--2324. doi:10.1109/5.726791"
    )
    assert e.authors == ["Yann LeCun", "Léon Bottou", "Yoshua Bengio"]  # accent decoded
    assert e.title == "Gradient-based learning applied to document recognition"
    assert (e.year, e.journal, e.entry_type) == (1998, "Proc. IEEE", "article")
    assert e.doi == "10.1109/5.726791"


def test_proceedings_of_the_ieee_is_a_journal():
    e = one(
        "\\bibitem{x} Y.~LeCun and L.~Bottou.\n\\newblock Gradient-based learning.\n"
        "\\newblock {\\em Proceedings of the IEEE}, 86(11):2278--2324, 1998."
    )
    assert e.entry_type == "article"


def test_thesis_has_no_journal():
    e = one(
        "\\bibitem{phd} J.~Smith.\n\\newblock Learning things.\n"
        "\\newblock PhD thesis, Stanford University, 2012."
    )
    assert (e.entry_type, e.journal, e.year) == ("phdthesis", None, 2012)


def test_doi_in_href_and_doi_command():
    a = one(
        "\\bibitem{a} A. B. Smith. Title here. J. Foo 1 (2020) 1. "
        "\\href{https://doi.org/10.1000/xyz.123}{doi}"
    )
    b = one("\\bibitem{b} A. B. Smith. Title here. J. Foo 1 (2020) 1. \\doi{10.1000/abc}.")
    assert a.doi == "10.1000/xyz.123" and b.doi == "10.1000/abc"


def test_commented_entries_and_other_commands_are_ignored():
    text = (
        "\\def\\bibitem{x}\n"
        "% \\bibitem{gone} Nobody. Hidden. 1999.\n"
        "\\bibitem{kept} A. Real. A title. 2001.\n"
        "\\bibitem{} A. Empty key. Skipped. 2002.\n"
    )
    assert [e.citation_key for e in parse_bibitems(text)] == ["kept"]


def test_entry_stops_at_end_of_thebibliography():
    text = (
        "\\begin{thebibliography}{9}\n\\bibitem{a} A. One. First title. 2001.\n"
        "\\end{thebibliography}\n\\section{Appendix} Text from 1850 that is not a reference.\n"
    )
    e = one(text)
    assert e.year == 2001 and "Appendix" not in e.raw


def test_revtex_bibinfo_names_the_fields():
    e = one(
        "\\bibitem[{Doe(2020{\\natexlab{a}})}]{doe20a}\n"
        "\\bibinfo{author}{\\bibfnamefont{J.}~\\bibnamefont{Doe}}, "
        "\\bibinfo{title}{A title worth reading}, \\bibinfo{journal}{Phys. Rev. Lett.} "
        "\\textbf{\\bibinfo{volume}{1}}, \\bibinfo{pages}{2} (\\bibinfo{year}{2020})"
    )
    assert e.authors == ["J. Doe"]
    assert (e.title, e.journal, e.year) == ("A title worth reading", "Phys. Rev. Lett.", 2020)


def test_year_in_parentheses_is_not_part_of_an_italic_title():
    e = one("\\bibitem{x} \\emph{A title worth reading} (2020).")
    assert e.title == "A title worth reading" and e.year == 2020


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A. Vaswani, N. Shazeer, and J. Uszkoreit", ["A. Vaswani", "N. Shazeer", "J. Uszkoreit"]),
        ("Vaswani, A., Shazeer, N.", ["A. Vaswani", "N. Shazeer"]),
        ("Vaswani, Ashish and Shazeer, Noam", ["Ashish Vaswani", "Noam Shazeer"]),
        ("Ada Lovelace and others", ["Ada Lovelace"]),
        ("J.-P. Serre, A. van der Waerden", ["J.-P. Serre", "A. van der Waerden"]),
        ("", []),
    ],
)
def test_parse_authors(text, expected):
    assert parse_authors(text) == expected


def test_find_year_prefers_label_then_parentheses_and_skips_page_ranges():
    assert find_year("pp. 1990--2005", None) is None
    assert find_year("Journal 3, 1990--2005, 2007", None) == 2007
    assert find_year("whatever (2011)", None) == 2011
    assert find_year("whatever 2011", "Smith(2015)Smith") == 2015


def test_to_row_matches_the_bibtex_table_columns():
    entry = BibEntry("k", "article", "T", ["A. B"], 2020, "10.1/x", "J", "http://u", raw="r")
    row = entry.to_row("2606.00001")
    columns = "arxiv_id citation_key entry_type title authors year doi journal url"
    assert list(row) == columns.split()  # the statement's `bibtex` table; `raw` stays out


def test_garbage_never_raises():
    rng = random.Random(7)
    alphabet = string.ascii_letters + string.digits + " \n{}[]\\$%&~.,:;\"'`()_^-"
    for _ in range(300):
        junk = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 200)))
        parse_bibitems("\\bibitem{k}" + junk)
        parse_bibitems("\\bibitem[" + junk + "]{k} " + junk)
        parse_bib("@article{k," + junk)


# ------------------------------------------------------------------ .bib


BIB = r"""
@string{nips = "Advances in Neural Information Processing Systems"}
@comment{ignored}
@article{lecun1998,
  author = {LeCun, Yann and Bottou, L{\'e}on and {Google Brain Team} and others},
  title = {Gradient-Based Learning Applied to {Document Recognition}},
  journal = {Proceedings of the IEEE},
  year = 1998,
  doi = {https://doi.org/10.1109/5.726791},
}
@inproceedings{vaswani2017,
  author = "Vaswani, Ashish and Shazeer, Noam",
  title = "Attention is all you need",
  booktitle = nips,
  year = {2017},
  eprint = {1706.03762},
  archivePrefix = {arXiv},
}
@misc{unused, title = {Never cited}, year = {2000}}
"""


def test_parse_bib_fields():
    entries = parse_bib(BIB)
    assert [e.citation_key for e in entries] == ["lecun1998", "vaswani2017", "unused"]
    a, b, _ = entries
    assert a.authors == ["Yann LeCun", "Léon Bottou", "Google Brain Team"]  # "others" dropped
    assert a.title == "Gradient-Based Learning Applied to Document Recognition"
    assert (a.entry_type, a.year, a.journal) == ("article", 1998, "Proceedings of the IEEE")
    assert a.doi == "10.1109/5.726791"
    assert b.journal == "Advances in Neural Information Processing Systems"  # @string expanded
    assert b.url == "https://arxiv.org/abs/1706.03762"


def test_cite_keys_covers_natbib_biblatex_and_options():
    text = (
        "See \\cite{a,b}, \\citep[p.~3]{c} and \\citet*{d}; \\parencite[see][]{e}.\n"
        "% \\cite{commented}\n\\citestyle{plain} \\nocite{f}"
    )
    assert cite_keys(text) == {"a", "b", "c", "d", "e", "f"}


# ------------------------------------------------------------------ a whole version


def make_version(tmp_path, files):
    vdir = tmp_path / "2606-00001" / "v1"
    for rel, text in files.items():
        (vdir / rel).parent.mkdir(parents=True, exist_ok=True)
        (vdir / rel).write_bytes(text.encode("utf-8"))
    return vdir


def refs_of(vdir):
    return extract_references(TexVersion(vdir), gather(vdir).files)


def test_bib_file_keeps_only_cited_entries_and_reports_the_rest(tmp_path):
    vdir = make_version(
        tmp_path,
        {
            "main.tex": "\\documentclass{article}\\begin{document}Known \\cite{lecun1998}, "
            "\\citep{vaswani2017}.\\bibliography{refs}\\end{document}",
            "refs.bib": BIB,
        },
    )
    refs = refs_of(vdir)
    assert [e.citation_key for e in refs.entries] == ["lecun1998", "vaswani2017"]
    assert (refs.bib_files, refs.n_bib_cited, refs.n_bib_unused) == (["refs.bib"], 2, 1)
    assert refs.missing_bib == []


def test_nocite_star_keeps_everything(tmp_path):
    vdir = make_version(
        tmp_path,
        {
            "main.tex": "\\documentclass{article}\\begin{document}\\nocite{*}"
            "\\bibliography{refs.bib}\\end{document}",
            "refs.bib": BIB,
        },
    )
    assert len(refs_of(vdir).entries) == 3


def test_bibitems_come_from_included_files_and_a_missing_bib_is_reported(tmp_path):
    vdir = make_version(
        tmp_path,
        {
            "main.tex": "\\documentclass{article}\\begin{document}\\input{refs}"
            "\\bibliography{gone}\\end{document}",
            "refs.tex": "\\begin{thebibliography}{9}\\bibitem{a} A. One. A title. 2001."
            "\\end{thebibliography}",
            "unused.tex": "\\bibitem{b} B. Two. Not in the PDF. 2002.",
        },
    )
    refs = refs_of(vdir)
    assert [e.citation_key for e in refs.entries] == ["a"]  # unused.tex is not reachable
    assert (refs.n_bibitems, refs.missing_bib) == (1, ["gone"])


def test_filecontents_bib_is_read(tmp_path):
    vdir = make_version(
        tmp_path,
        {
            "main.tex": "\\documentclass{article}\n"
            "\\begin{filecontents}{embedded.bib}\n@book{k1, title={Inline}, year={1999}}\n"
            "\\end{filecontents}\n\\begin{document}\\cite{k1}\\bibliography{embedded}"
            "\\end{document}",
        },
    )
    refs = refs_of(vdir)
    assert [(e.citation_key, e.source, e.year) for e in refs.entries] == [
        ("k1", "filecontents", 1999)
    ]
    assert refs.missing_bib == []


def test_cli_prints_the_entries(tmp_path, capsys):
    body = "\\bibitem{a} A. One. A title. 2001."
    vdir = make_version(
        tmp_path,
        {"main.tex": f"\\documentclass{{article}}\\begin{{document}}{body}\\end{{document}}"},
    )
    assert main([str(vdir), "--json"]) == 0
    out = capsys.readouterr()
    assert '"citation_key": "a"' in out.out and "1 entries" in out.err


def test_a_kept_bbl_is_read_back_when_nothing_else_has_references(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Text \cite{a}.\end{document}", encoding="utf-8"
    )
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{1}\n\\bibitem{a} A. Author and B. Writer.\n"
        "\\newblock A title of the paper.\n\\newblock {\\em Journal}, 2020.\n"
        "\\end{thebibliography}\n",
        encoding="utf-8",
    )
    tex = TexVersion(tmp_path)
    refs = extract_references(tex, gather(tmp_path).files)
    assert [e.citation_key for e in refs.entries] == ["a"]
    assert refs.entries[0].source == "bbl" and refs.entries[0].year == 2020
    assert refs.bbl_files == ["main.bbl"]


def test_a_bbl_is_ignored_when_the_tex_has_its_own_bibitems(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\begin{thebibliography}{1}"
        r"\bibitem{k} A. B. Title. 2001.\end{thebibliography}\end{document}",
        encoding="utf-8",
    )
    (tmp_path / "main.bbl").write_text(r"\bibitem{other} X. Y. Other. 1999.", encoding="utf-8")
    refs = extract_references(TexVersion(tmp_path), gather(tmp_path).files)
    assert [e.citation_key for e in refs.entries] == ["k"] and refs.bbl_files == []


def test_external_bbl_is_used_when_tex_has_no_references(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Text.\end{document}", encoding="utf8"
    )
    external = tmp_path / "external.bbl"
    external.write_text(r"\bibitem{external} A. Author. A title. 2020.", encoding="utf8")
    refs = extract_references(TexVersion(corpus), gather(corpus).files, external_bbl=[external])
    assert [entry.citation_key for entry in refs.entries] == ["external"]
    assert not (corpus / "external.bbl").exists()


def test_external_bbl_does_not_override_tex_bibitems(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\bibitem{inside} "
        r"A. Author. Inside. 2001.\end{document}",
        encoding="utf8",
    )
    external = tmp_path / "external.bbl"
    external.write_text(r"\bibitem{outside} B. Author. Outside. 2020.", encoding="utf8")
    refs = extract_references(TexVersion(corpus), gather(corpus).files, external_bbl=[external])
    assert [entry.citation_key for entry in refs.entries] == ["inside"]
    assert refs.bbl_files == []


def test_local_and_external_bbl_conflict_is_reported(tmp_path):
    import pytest

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "main.tex").write_text(r"\documentclass{article}\begin{document}Text.\end{document}")
    (corpus / "local.bbl").write_text(r"\bibitem{local} Local.")
    external = tmp_path / "external.bbl"
    external.write_text(r"\bibitem{external} External.")
    with pytest.raises(ValueError, match="Both local and external"):
        extract_references(TexVersion(corpus), gather(corpus).files, external_bbl=[external])


def test_external_bbl_changed_after_preflight_is_rejected(tmp_path):
    import hashlib

    import pytest

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "main.tex").write_text(r"\documentclass{article}\begin{document}Text.\end{document}")
    external = tmp_path / "external.bbl"
    content = b"\\bibitem{x} A. Author. Title. 2020."
    external.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    external.write_bytes(b"X" * len(content))
    with pytest.raises(ValueError, match="BBL integrity"):
        extract_references(
            TexVersion(corpus),
            gather(corpus).files,
            external_bbl=[external],
            external_hashes={external: expected},
        )
