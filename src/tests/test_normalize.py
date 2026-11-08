# Drafted with the help of an AI assistant (Claude, Anthropic), cited per the course rules.
import pytest

from src.parser.normalize import (
    match_brace,
    normalize,
    normalize_math,
    strip_formatting,
    unwrap_command,
)


def test_comments_are_removed_but_escaped_percent_stays():
    out = normalize("Accuracy is 95\\% % this is a comment\nNext line")
    assert "comment" not in out and "95\\%" in out


@pytest.mark.parametrize("src", [r"\(a+b\)", r"$a+b$", r"\begin{math}a+b\end{math}"])
def test_inline_math_has_one_spelling(src):
    assert normalize_math(f"x {src} y") == "x $a+b$ y"


@pytest.mark.parametrize(
    "src",
    [
        "$$ E = mc^2 $$",
        r"\[ E = mc^2 \]",
        r"\begin{equation*} E = mc^2 \end{equation*}",
        r"\begin{displaymath} E = mc^2 \end{displaymath}",
        r"\begin{equation} E = mc^2 \label{eq:1} \end{equation}",
        r"\begin{equation} E = mc^2 \nonumber \end{equation}",
    ],
)
def test_block_math_is_an_equation_environment(src):
    out = normalize(src).strip()
    assert out == "\\begin{equation}\nE = mc^2\n\\end{equation}"


def test_multi_line_environments_keep_their_lines_in_aligned():
    out = normalize(r"\begin{align} a &= b \\ c &= d \end{align}")
    assert (
        "\\begin{equation}" in out and "\\begin{aligned} a &= b \\\\ c &= d \\end{aligned}" in out
    )
    assert "\\begin{align}" not in out
    out = normalize(r"\begin{gather*} a \\ b \end{gather*}")
    assert "\\begin{gathered}" in out


def test_dollar_signs_that_are_not_math_are_left_alone():
    out = normalize_math(r"It costs \$5 and \$6. Then $x$ holds.")
    assert out == r"It costs \$5 and \$6. Then $x$ holds."


def test_a_lone_dollar_does_not_swallow_a_paragraph():
    text = "Price: 5$ here.\n\nAnother paragraph with $x$."
    assert normalize_math(text).endswith("$x$.")


def test_formatting_commands_are_dropped():
    src = (
        "\\begin{figure}[htbp]\n\\centering\n\\includegraphics{a.pdf}\n\\caption{Cap}\n"
        "\\label{fig:a}\n\\end{figure}\n\\begin{tabular}{ll}\n\\toprule\na & b \\\\\n"
        "\\midrule\nc & d \\\\\n\\bottomrule\n\\end{tabular}\n\\vspace{1em}\\noindent Text"
    )
    out = normalize(src)
    for gone in (
        "htbp",
        "centering",
        "toprule",
        "midrule",
        "bottomrule",
        "vspace",
        "noindent",
        "label",
    ):
        assert gone not in out, gone
    assert (
        "\\begin{figure}" in out and "\\includegraphics{a.pdf}" in out and "\\caption{Cap}" in out
    )


def test_text_styles_are_unwrapped_nested_too():
    assert strip_formatting(r"\textbf{a \emph{b} c}") == "a b c"


def test_unbalanced_style_command_does_not_loop():
    assert unwrap_command(r"\textbf{oops", "textbf") == "oops"


def test_match_brace_skips_escaped_braces():
    assert match_brace(r"{a \} b}", 0) == len(r"{a \} b}")


def test_idempotent():
    once = normalize("$$a$$ and \\(b\\) \\textbf{c}\n\n\n\nd")
    assert normalize(once) == once
