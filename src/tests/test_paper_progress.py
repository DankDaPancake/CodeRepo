from src.run_pipeline import PaperProgress


def test_progress_counts_only_papers_with_all_versions_and_handles_resume(tmp_path, caplog):
    found = {str(i): (2 if i == 10 else 1) for i in range(1, 22)}
    state = {}
    progress = PaperProgress(found, state, tmp_path)

    def record(paper, version, status="ok"):
        rec = {"arxiv_id": str(paper), "version": version, "status": status}
        (tmp_path / str(paper) / f"v{version}").mkdir(parents=True, exist_ok=True)
        state[(str(paper), version)] = rec
        progress.record(str(paper))

    with caplog.at_level("INFO"):
        for i in range(1, 10):
            record(i, 1)
        record(10, 1)
        assert "PAPER_PROGRESS" not in caplog.text
        record(10, 2, status="failed")
        assert "PAPER_PROGRESS" not in caplog.text
        record(10, 2)
        assert "PAPER_PROGRESS source_terminal=10/21" in caplog.text
        record(10, 2)
        for i in range(11, 21):
            record(i, 1)
    assert caplog.text.count("PAPER_PROGRESS") == 2
    assert "PAPER_PROGRESS source_terminal=20/21" in caplog.text
    resumed = PaperProgress(found, state, tmp_path)
    with caplog.at_level("INFO"):
        (tmp_path / "21" / "v1").mkdir(parents=True)
        state[("21", 1)] = {"arxiv_id": "21", "version": 1, "status": "ok"}
        resumed.record("21")
    assert caplog.text.count("PAPER_PROGRESS") == 3
    assert "source_terminal=21/21" in caplog.text


def test_forward_only_complete_progress_lines(tmp_path, capsys):
    from src.benchmark.runner import forward_paper_progress

    path = tmp_path / "console.log"
    path.write_bytes(b"noise\nPAPER_PROGRESS source_terminal=10/100\nPAPER_PRO")
    offset = forward_paper_progress(path, 0)
    assert "source_terminal=10/100" in capsys.readouterr().out
    with path.open("ab") as f:
        f.write(b"GRESS source_terminal=20/100\n")
    offset = forward_paper_progress(path, offset)
    assert "source_terminal=20/100" in capsys.readouterr().out
    assert forward_paper_progress(path, offset) == offset
    assert capsys.readouterr().out == ""


def test_progress_reports_final_partial_group(tmp_path, caplog):
    found = {str(i): 1 for i in range(27)}
    state = {}
    progress = PaperProgress(found, state, tmp_path)
    with caplog.at_level("INFO"):
        for paper in found:
            (tmp_path / paper / "v1").mkdir(parents=True)
            state[(paper, 1)] = {"arxiv_id": paper, "version": 1, "status": "ok"}
            progress.record(paper)
    assert "source_terminal=10/27" in caplog.text
    assert "source_terminal=20/27" in caplog.text
    assert "source_terminal=27/27" in caplog.text
