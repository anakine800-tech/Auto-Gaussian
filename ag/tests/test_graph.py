import json

from ag.cli import main
from ag.graph import read_graph, tree_text


def attempt(tmp_path, name, parents=()):
    path = tmp_path / "attempts" / name
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps({
        "attempt_id": name, "template": "gaussian", "label": "optfreq",
        "parents": [{"attempt_id": parent, "relation": "conformer_of"} for parent in parents]}))
    (path / "status.json").write_text(json.dumps({"state": "fetched"}))


def test_three_levels_and_missing_parent(tmp_path, capsys):
    attempt(tmp_path, "a")
    attempt(tmp_path, "b", ["a"])
    attempt(tmp_path, "c", ["b"])
    attempt(tmp_path, "d", ["missing"])
    graph = read_graph(tmp_path)
    text = tree_text(graph)
    assert "\n  (conformer_of) b" in text
    assert "\n    (conformer_of) c" in text
    assert "missing [missing parent]" in text
    assert "gaussian | optfreq | fetched" in text
    assert main(["graph", "--study", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == graph


def test_shared_children_cycles_and_missing_status(tmp_path):
    attempt(tmp_path, "a", ["c"])
    attempt(tmp_path, "b", ["a"])
    attempt(tmp_path, "c", ["a", "b"])
    (tmp_path / "attempts" / "a" / "status.json").unlink()
    graph = read_graph(tmp_path)
    assert len(graph["edges"]) == 4
    text = tree_text(graph)
    assert "unavailable" in text
    assert "[already shown]" in text
    assert len(text.splitlines()) == 5


def test_empty_and_invalid_study(tmp_path, capsys):
    assert main(["graph", "--study", str(tmp_path)]) == 1
    capsys.readouterr()
    (tmp_path / "attempts").mkdir()
    assert main(["graph", "--study", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "No Attempts."
