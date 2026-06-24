from pathlib import Path

from web_researcher.report import save_report


def test_save_report_writes_file_with_frontmatter(tmp_path: Path):
    path = save_report(
        "What is the airspeed velocity of an unladen swallow?",
        "# Answer\n\nAfrican or European?\n",
        tmp_path,
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "question:" in text
    assert "African or European?" in text
    assert "what-is-the-airspeed" in path.name
