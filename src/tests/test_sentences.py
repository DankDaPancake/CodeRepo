# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
import pytest

from src.parser.sentences import split_sentences


@pytest.mark.parametrize(
    "text, expected",
    [
        ("We train a model. It works well. Does it scale? Yes!", 4),
        # abbreviations
        ("We use CNNs, e.g. ResNet, on images.", 1),
        ("The gain is large, i.e. 5 points. See below.", 2),
        ("This was shown by Smith et al. in 2020. It holds.", 2),
        ("As shown in Fig. 3 the loss drops. Eq. 4 explains why.", 2),
        ("See Sec. 2 and Tab. 1 for details.", 1),
        ("Compare with Ref. [3], cf. Section 4, vs. the baseline.", 1),
        ("We collect images, videos, etc. Then we train.", 2),
        ("We collect images, videos, etc. and train.", 1),
        # numbers, URLs, files
        ("The value is 3.14 on average. Next we repeat it.", 2),
        ("Code is at https://github.com/a/b.git and www.example.org. We release it.", 2),
        ("Run main.py with the flag. The result is saved.", 2),
        ("Contact john.doe@mail.example.com for data. Thanks.", 2),
        # initials
        ("The method of J. Smith and A. B. Jones works. It is old.", 2),
        ("The U.S. government funded this. It helped.", 2),
        # lower-case after the period is not a boundary
        ("We use approx. five layers.", 1),
        ("The set {1, 2, ...} is infinite.", 1),
    ],
)
def test_number_of_sentences(text, expected):
    assert len(split_sentences(text)) == expected, split_sentences(text)


def test_no_split_inside_math_and_commands():
    text = r"Let $x = 1. 5$ and $y \in A.$ Then \cite{a.b, c.d} and \ref{fig:1.2} hold. Done."
    got = split_sentences(text)
    assert got == [
        r"Let $x = 1. 5$ and $y \in A.$ Then \cite{a.b, c.d} and \ref{fig:1.2} hold.",
        "Done.",
    ]


def test_citation_after_the_period_stays_with_its_sentence():
    got = split_sentences(r"Prior work exists.\cite{a,b} We build on it.\cite{c} End.")
    assert got == [r"Prior work exists.\cite{a,b}", r"We build on it.\cite{c}", "End."]


def test_url_command_and_href_are_not_split():
    got = split_sentences(
        r"See \url{http://a.org/x.html}. Also \href{http://b.org/y.pdf}{this}. Done."
    )
    assert len(got) == 3


def test_quotes_and_brackets_close_the_sentence():
    got = split_sentences("He said ``stop.'' Then he left. (It was late.) We went home.")
    assert got[0].endswith("''") and len(got) == 4


def test_whitespace_is_collapsed_and_empty_input_is_empty():
    assert split_sentences("  A   b.\n\n  C d. ") == ["A b.", "C d."]
    assert split_sentences("   ") == []


def test_a_sentence_may_start_with_a_command_or_math():
    got = split_sentences(r"First point. \textbf{Second} point. $x$ is small.")
    assert len(got) == 3


def test_list_number_alone_is_not_a_sentence_end():
    assert len(split_sentences("1. Introduction")) == 1
    assert len(split_sentences("See Table 1. The results follow.")) == 2
