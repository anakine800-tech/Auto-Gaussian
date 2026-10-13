from dataclasses import replace
import json
from pathlib import Path

import pytest

from ag import geometry as g
from ag.cli import main
from ag.dedup import deduplicate

DATA = Path(__file__).parent / "data" / "butane.xyz"


def dedup(frames, **kwargs):
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds, rdMolAlign
    return deduplicate(frames, kwargs.get("charge", 0), kwargs.get("rmsd", 0.125),
                       kwargs.get("de", 0.05), kwargs.get("window", 3.0),
                       Chem, rdDetermineBonds, rdMolAlign)


def test_anti_gauche_duplicate_and_window():
    frames = g.read_xyz(DATA)
    frames.extend([replace(frames[0], energy=-156.99999), replace(frames[1], energy=-156.9)])
    kept, excluded, selected = dedup(frames)
    assert [r["index"] for r in kept] == [1, 2, 3]
    assert [r["reason"] for r in excluded] == ["duplicate", "energy_window"]
    assert excluded[0]["representative"] == 1
    assert kept[1]["relative_energy_kcal"] == pytest.approx(0.627509474)
    assert len(selected) == 3


def test_lower_energy_kept_and_energy_difference_required():
    frames = g.read_xyz(DATA)
    frames = [frames[0], replace(frames[0], energy=-157.00001), replace(frames[0], energy=-156.999)]
    kept, excluded, _ = dedup(frames)
    assert [r["index"] for r in kept] == [2, 3]
    assert excluded[0]["index"] == 1


def test_changed_graph_and_inference_failure():
    from rdkit import Chem
    from rdkit.Chem import AllChem
    frames = g.read_xyz(DATA)
    # Isobutane: same formula, different connectivity; synthetic geometry only.
    mol = Chem.AddHs(Chem.MolFromSmiles("CC(C)C"))
    assert AllChem.EmbedMolecule(mol, randomSeed=7) == 0
    changed = replace(frames[0], coordinates=tuple(tuple(p) for p in mol.GetConformer().GetPositions()),
                      energy=-158)
    broken = replace(frames[0], coordinates=tuple((x * 100, y * 100, z * 100)
                                                 for x, y, z in frames[0].coordinates))
    kept, excluded, _ = dedup(frames + [changed, broken])
    assert len(kept) == 3  # Rejected lower energy does not move the window zero.
    assert [r["reason"] for r in excluded] == ["graph_changed", "bond_inference_failed"]


def test_attempt_facts_and_cli(tmp_path, capsys):
    frames = g.read_xyz(DATA)
    inputs = []
    for index, frame in enumerate(frames):
        attempt = tmp_path / f"attempt-{index}"
        attempt.mkdir()
        g.write_xyz(attempt / "final.xyz", [replace(frame, energy=None, comment="")])
        (attempt / "facts.json").write_text(json.dumps({"energies": {"scf": frame.energy}}))
        inputs.append(str(attempt))
    assert main(["dedup", *inputs, "--charge", "0", "--out", str(tmp_path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["kept"]) == 3
    assert Path(result["output"]).exists()
    assert main(["dedup", *inputs, "--charge", "0", "--rmsd", "nan", "--out", str(tmp_path)]) == 1
    assert "finite" in capsys.readouterr().err


def test_missing_energy_is_error(tmp_path, capsys):
    path = tmp_path / "no-energy.xyz"
    g.write_xyz(path, [replace(g.read_xyz(DATA)[0], energy=None, comment="")])
    assert main(["dedup", str(path), "--charge", "0", "--out", str(tmp_path)]) == 1
    assert "Missing energy" in capsys.readouterr().err
    assert not list(tmp_path.glob("dedup-*"))


@pytest.mark.parametrize("smiles_pair", [("C[C@H](O)CC", None), ("C/C=C/C", "C/C=C\\C")])
def test_stereo_changes_are_excluded_before_energy_window(tmp_path, smiles_pair):
    from rdkit import Chem
    from rdkit.Chem import AllChem

    def frame_from_smiles(smiles, name):
        mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
        assert AllChem.EmbedMolecule(mol, randomSeed=31) == 0
        path = tmp_path / name
        path.write_text(Chem.MolToXYZBlock(mol))
        return replace(g.read_xyz(path)[0], energy=-10.0)

    first = frame_from_smiles(smiles_pair[0], "reference.xyz")
    changed = (frame_from_smiles(smiles_pair[1], "changed.xyz") if smiles_pair[1]
               else replace(first, coordinates=tuple((-x, -y, -z) for x, y, z in first.coordinates)))
    changed = replace(changed, energy=-11.0, source_frame=2)
    # An atom permutation and proper rotation preserve the stereoisomer.
    same = replace(first, symbols=first.symbols[::-1],
                   coordinates=tuple((y + 3, -x + 2, z + 1) for x, y, z in first.coordinates[::-1]),
                   energy=-9.999, source_frame=3)
    kept, excluded, _ = dedup([first, changed, same])
    assert [row["index"] for row in kept] == [1, 3]
    assert kept[0]["relative_energy_kcal"] == 0
    assert len(excluded) == 1
    assert excluded[0]["index"] == 2
    assert excluded[0]["source_frame"] == 2
    assert excluded[0]["reason"] == "stereo_changed"


def test_out_is_required_and_missing_out_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["dedup", str(DATA), "--charge", "0"])
    assert exc.value.code == 2
    assert "--out" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
    with pytest.raises(SystemExit) as exc:
        main(["dedup", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "study's analyses/" in help_text


def test_charged_structure_uses_supplied_charge(tmp_path):
    from rdkit import Chem
    from rdkit.Chem import AllChem
    mol = Chem.AddHs(Chem.MolFromSmiles("C[NH3+]"))
    assert AllChem.EmbedMolecule(mol, randomSeed=5) == 0
    path = tmp_path / "ion.xyz"
    path.write_text(Chem.MolToXYZBlock(mol))
    frame = replace(g.read_xyz(path)[0], energy=-10.0)
    assert len(dedup([frame], charge=1)[0]) == 1
    with pytest.raises(ValueError):
        dedup([frame], charge=0)


def test_performance_200_frames_20_heavy_atoms(tmp_path):
    """Reproducible all-pairs workload; generation is outside the timed region."""
    import time
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.AddHs(Chem.MolFromSmiles("C" * 20))
    params = AllChem.ETKDGv3()
    params.randomSeed = 20261013
    params.numThreads = 1
    params.pruneRmsThresh = -1
    ids = AllChem.EmbedMultipleConfs(mol, numConfs=200, params=params)
    assert len(ids) == 200
    path = tmp_path / "ensemble.xyz"
    with path.open("w") as handle:
        for cid in ids:
            lines = Chem.MolToXYZBlock(mol, confId=cid).splitlines()
            lines[1] = str(-100.0 + cid * 0.0000001)
            handle.write("\n".join(lines) + "\n")
    start = time.perf_counter()
    kept, excluded, _ = dedup(g.load_frames([path]))
    elapsed = time.perf_counter() - start
    print(f"200 frames / 20 heavy atoms: {elapsed:.3f} s; kept={len(kept)}")
    assert len(kept) == 200
    assert not excluded
    assert elapsed < 60
