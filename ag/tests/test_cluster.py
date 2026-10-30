from dataclasses import replace
import json
from pathlib import Path

import pytest

from ag import geometry as g
from ag.cli import main
from ag.cluster import select

DATA = Path(__file__).parent / "data" / "butane.xyz"


def cluster(frames, maximum=20, rmsd=0.5, mirror=True):
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds, rdMolAlign
    energies = g.relative_energies(frames, min(f.energy for f in frames))
    rows = [g.record(f, i, energies[i]) for i, f in enumerate(frames)]
    return select(frames, rows, 0, maximum, rmsd, mirror, Chem, rdDetermineBonds, rdMolAlign)


def test_mirror_degeneracy_and_cap():
    frames = g.read_xyz(DATA)
    reps, excluded, _ = cluster(frames, maximum=2)
    assert [r["degeneracy"] for r in reps] == [1, 2]
    assert [m["index"] for m in reps[1]["members"]] == [2, 3]
    assert reps[1]["members"][1]["reason"] == "mirror"
    assert not excluded
    assert len(cluster(frames, rmsd=0.125, mirror=False)[0]) == 3
    reps, excluded, _ = cluster(frames, maximum=1)
    assert len(reps) == 1
    assert len(excluded) == 2


def test_direct_duplicates_do_not_add_degeneracy():
    frame = g.read_xyz(DATA)[0]
    reps, _, _ = cluster([frame, frame])
    assert len(reps) == 1
    assert reps[0]["degeneracy"] == 1


def test_mirror_energy_tolerance():
    frames = g.read_xyz(DATA)
    frames[2] = replace(frames[2], energy=frames[2].energy + 0.1 / g.HARTREE_TO_KCAL)
    assert len(cluster(frames, rmsd=0.125)[0]) == 3
    with pytest.raises(ValueError, match="positive"):
        cluster(frames, maximum=0)


def test_full_cli_outputs_no_overwrite(tmp_path, capsys, butane_xyz):
    assert main(["dedup", str(butane_xyz), "--charge", "0", "--out", str(tmp_path), "--json"]) == 0
    dedup = json.loads(capsys.readouterr().out)
    for _ in range(2):
        assert main(["cluster", dedup["output"], "--mirror", "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert [r["degeneracy"] for r in result["representatives"]] == [1, 2]
        for rep in result["representatives"]:
            assert len(g.read_xyz(tmp_path / rep["xyz_file"])) == 1
    assert len(list(tmp_path.glob("cluster-*.json"))) == 2
    assert len(list(tmp_path.glob("cluster-*.xyz"))) == 4


def test_stale_dedup_energy_rejected(tmp_path, capsys, butane_xyz):
    assert main(["dedup", str(butane_xyz), "--charge", "0", "--out", str(tmp_path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    path = Path(result["output"])
    payload = json.loads(path.read_text())
    payload["kept"][0]["energy"] = 42
    path.write_text(json.dumps(payload))
    assert main(["cluster", str(path), "--mirror"]) == 1
    assert "do not agree" in capsys.readouterr().err


def test_chiral_mirror_rejected_without_output(tmp_path, capsys):
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.AddHs(Chem.MolFromSmiles("C[C@H](O)CC"))
    assert AllChem.EmbedMolecule(mol, randomSeed=31) == 0
    path = tmp_path / "butanol.xyz"
    lines = Chem.MolToXYZBlock(mol).splitlines()
    lines[1] = "-10.0"
    path.write_text("\n".join(lines) + "\n")
    assert main(["dedup", str(path), "--charge", "0", "--out", str(tmp_path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert main(["cluster", result["output"], "--mirror"]) == 1
    assert "镜像简并只适用于非手性分子" in capsys.readouterr().err
    assert not list(tmp_path.glob("cluster-*"))
    # Ordinary selection of a chiral molecule is still supported.
    assert main(["cluster", result["output"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["representatives"][0]["degeneracy"] == 1
