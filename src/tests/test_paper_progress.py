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
        assert "source_terminal=9/21" in caplog.text
        assert "source_terminal=10/21" not in caplog.text
        record(10, 2, status="failed")
        assert "source_terminal=10/21" not in caplog.text
        record(10, 2)
        assert "PAPER_PROGRESS source_terminal=10/21" in caplog.text
        record(10, 2)
        for i in range(11, 21):
            record(i, 1)
    assert caplog.text.count("PAPER_PROGRESS") == 20
    assert "PAPER_PROGRESS source_terminal=20/21" in caplog.text
    resumed = PaperProgress(found, state, tmp_path)
    with caplog.at_level("INFO"):
        (tmp_path / "21" / "v1").mkdir(parents=True)
        state[("21", 1)] = {"arxiv_id": "21", "version": 1, "status": "ok"}
        resumed.record("21")
    assert caplog.text.count("PAPER_PROGRESS") == 21
    assert "source_terminal=21/21" in caplog.text


def test_forward_only_complete_progress_lines(tmp_path):
    from src.benchmark.runner import forward_paper_progress

    path = tmp_path / "console.log"
    path.write_bytes(b"noise\nPAPER_PROGRESS source_terminal=10/100\nPAPER_PRO")
    seen = []
    offset = forward_paper_progress(path, 0, lambda n, total: seen.append((n, total)))
    assert seen == [(10, 100)]
    with path.open("ab") as f:
        f.write(b"GRESS source_terminal=20/100\n")
    offset = forward_paper_progress(path, offset, lambda n, total: seen.append((n, total)))
    assert seen == [(10, 100), (20, 100)]
    assert forward_paper_progress(path, offset, lambda n, total: seen.append((n, total))) == offset
    assert len(seen) == 2


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


def test_progress_emits_each_completed_paper_including_resumed_initial_state(tmp_path, caplog):
    found = {str(i): 1 for i in range(3)}
    (tmp_path / "0" / "v1").mkdir(parents=True)
    state = {("0", 1): {"arxiv_id": "0", "version": 1, "status": "ok"}}
    with caplog.at_level("INFO"):
        progress = PaperProgress(found, state, tmp_path)
        for paper in ("1", "2"):
            (tmp_path / paper / "v1").mkdir(parents=True)
            state[(paper, 1)] = {"arxiv_id": paper, "version": 1, "status": "ok"}
            progress.record(paper)
    assert "source_terminal=1/3" in caplog.text
    assert "source_terminal=2/3" in caplog.text
    assert "source_terminal=3/3" in caplog.text


def test_forward_progress_updates_bar_without_reprinting_lines(tmp_path):
    from src.benchmark.runner import forward_paper_progress

    path = tmp_path / "console.log"
    path.write_bytes(b"noise\nPAPER_PROGRESS source_terminal=2/3 more\nPAPER_PRO")
    seen = []
    offset = forward_paper_progress(path, 0, lambda n, total: seen.append((n, total)))
    with path.open("ab") as f:
        f.write(b"GRESS source_terminal=3/3\n")
    forward_paper_progress(path, offset, lambda n, total: seen.append((n, total)))
    assert seen == [(2, 3), (3, 3)]
