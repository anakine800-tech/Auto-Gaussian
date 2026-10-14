"""Synthetic coordinates only: distinguish OH rotors without retaining methyl rotors."""

from dataclasses import replace
import json
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdDetermineBonds, rdMolAlign, rdMolTransforms

from ag import geometry as geo
from ag.cli import main
from ag.cluster import select
from ag.coverage import report
from ag.dedup import deduplicate
from test_sampling import attempt


@pytest.fixture
def ethanol():
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert AllChem.EmbedMolecule(mol, randomSeed=28) == 0
    oh = next(a.GetIdx() for a in mol.GetAtomWithIdx(2).GetNeighbors() if a.GetAtomicNum() == 1)
    methyl_h = next(a.GetIdx() for a in mol.GetAtomWithIdx(0).GetNeighbors() if a.GetAtomicNum() == 1)

    def frame():
        return geo.Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()),
                         tuple(tuple(p) for p in mol.GetConformer().GetPositions()), energy=-154.0)

    rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 0, 1, 2, oh, 60)
    first = frame()
    rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 0, 1, 2, oh, 180)
    oh_rotated = frame()
    rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 0, 1, 2, oh, 60)
    angle = rdMolTransforms.GetDihedralDeg(mol.GetConformer(), 2, 1, 0, methyl_h)
    rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 2, 1, 0, methyl_h, angle + 60)
    return first, oh_rotated, frame()


def dedup(frames, **kwargs):
    return deduplicate(frames, 0, 0.125, kwargs.pop("de", 0.05), 3,
                       Chem, rdDetermineBonds, rdMolAlign, **kwargs)


@pytest.mark.parametrize("mode,count", [("polar", 2), ("heavy", 1), ("all", 2)])
def test_oh_rotor_and_no_coordinate_or_atom_order_mutation(ethanol, mode, count):
    frames = list(ethanol[:2])
    before = geo.xyz_text(frames)
    kept, excluded, selected = dedup(frames, hydrogens=mode)
    assert len(kept) == count
    assert geo.xyz_text(frames) == before
    assert selected == frames[:count]
    if count == 1:
        assert excluded[0]["rmsd"] < 1e-6
        assert excluded[0]["heavy_rmsd"] == pytest.approx(excluded[0]["rmsd"])
    assert len(dedup(frames)[0]) == 2  # Default is polar.


def test_methyl_rotation_and_two_rmsds(ethanol):
    frames = [ethanol[0], ethanol[2]]
    assert len(dedup(frames)[0]) == 1
    assert len(dedup(frames, hydrogens="all")[0]) == 2
    # A small OH change merges, but its selected-atom RMSD is nonzero.
    mol = geo.infer_molecule(ethanol[0], 0, Chem, rdDetermineBonds)
    oh = next(a.GetIdx() for a in mol.GetAtomWithIdx(2).GetNeighbors() if a.GetAtomicNum() == 1)
    rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 0, 1, 2, oh, 70)
    changed = replace(ethanol[0], coordinates=tuple(tuple(p) for p in mol.GetConformer().GetPositions()))
    kept, excluded, _ = dedup([ethanol[0], changed])
    assert len(kept) == 1
    assert excluded[0]["heavy_rmsd"] < 1e-6
    assert 0.001 < excluded[0]["rmsd"] < 0.125


@pytest.mark.parametrize("mode", ["heavy", "polar", "all"])
def test_symmetry_equivalent_hydrogens_merge(ethanol, mode):
    first = ethanol[0]
    mol = geo.infer_molecule(first, 0, Chem, rdDetermineBonds)
    hs = [a.GetIdx() for a in mol.GetAtomWithIdx(0).GetNeighbors() if a.GetAtomicNum() == 1]
    xyz = list(first.coordinates)
    xyz[hs[0]], xyz[hs[1]] = xyz[hs[1]], xyz[hs[0]]
    same = replace(first, coordinates=tuple((y + 3, -x + 2, z + 1) for x, y, z in xyz))
    kept, excluded, selected = dedup([first, same], hydrogens=mode)
    assert len(kept) == 1
    assert excluded[0]["rmsd"] < 1e-6
    assert selected == [first]


@pytest.mark.parametrize("smiles", ["CN", "CO", "CS", "CP"])
def test_polar_selection_uses_bonded_element(smiles):
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    expected = tuple(a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() != 1 or
                     a.GetNeighbors()[0].GetIdx() == 1)
    assert geo.atom_indices(mol, "polar") == expected
    assert geo.atom_indices(mol, "heavy") == (0, 1)
    assert geo.atom_indices(mol, "all") == tuple(range(mol.GetNumAtoms()))
    with pytest.raises(ValueError, match="hydrogen mode"):
        geo.atom_indices(mol, "unknown")


def merge(tmp_path, capsys, frames, *options):
    args = ["dedup", "--charge", "0", "--out", str(tmp_path), "--json", *options]
    for i, frame in enumerate(frames):
        path = tmp_path / f"source-{i}.xyz"
        path.write_text(geo.xyz_text([frame]))
        args += ["--source", f"route{i}={path}"]
    assert main(args) == 0
    return json.loads(capsys.readouterr().out)


def test_lowest_source_energy_tolerance_cli_and_provenance(tmp_path, capsys, ethanol):
    first = ethanol[0]
    higher = replace(first, energy=first.energy + 0.1 / geo.HARTREE_TO_KCAL)
    result = merge(tmp_path, capsys, [higher, first], "--representative", "lowest")
    assert result["hydrogens"] == "polar" and result["de_kcal"] == 0.05
    assert [r["index"] for r in result["kept"]] == [2, 1]
    assert [r["sources"] for r in result["kept"]] == [["route1"], ["route0"]]
    result = merge(tmp_path, capsys, [higher, first], "--representative", "lowest", "--de", "0.2")
    assert len(result["kept"]) == 1 and result["kept"][0]["index"] == 2
    assert result["de_kcal"] == 0.2
    assert result["kept"][0]["sources"] == ["route0", "route1"]
    assert {"rmsd", "heavy_rmsd"} <= result["excluded"][0].keys()
    # Geometry-only merging remains independent of energies and their units.
    result = merge(tmp_path, capsys, [first, replace(higher, energy=50, energy_unit="kcal/mol")])
    assert len(result["kept"]) == 1 and result["de_kcal"] is None
    assert main(["dedup", "--source", f"a={tmp_path / 'source-0.xyz'}", "--de", "0.1",
                 "--charge", "0", "--out", str(tmp_path)]) == 1
    assert "geometry-only" in capsys.readouterr().err


@pytest.mark.parametrize("mode,count", [("polar", 2), ("heavy", 1), ("all", 2)])
def test_cluster_and_coverage_inherit_mode(tmp_path, capsys, ethanol, mode, count):
    # Keep both frames in dedup to exercise clustering's own merge decisions.
    result = merge(tmp_path, capsys, ethanol[:2], "--hydrogens", mode, "--rmsd", "0")
    assert len(result["kept"]) == 2 and result["hydrogens"] == mode
    for representative in ("lowest", "medoid"):
        # Energy comparison is explicitly enabled for lowest.
        ranked = merge(tmp_path, capsys, ethanol[:2], "--hydrogens", mode, "--rmsd", "0",
                       "--representative", "lowest")
        assert main(["cluster", ranked["output"], "--rmsd", "0.125", "--representative",
                     representative, "--json"]) == 0
        clustered = json.loads(capsys.readouterr().out)
        assert clustered["hydrogens"] == mode
        assert len(clustered["representatives"]) == count
        if count == 1:
            member = clustered["representatives"][0]["members"][1]
            assert member["rmsd"] < 1e-6 and member["heavy_rmsd"] < 1e-6
    path = attempt(tmp_path, ethanol[1], "oh-rotor")
    coverage = report(result["output"], [str(path)])
    assert coverage["hydrogens"] == mode
    if mode == "heavy":
        assert coverage["n_matched"] == 0  # Both candidates match: fail closed on ambiguity.
        assert coverage["unmatched_attempts"][0]["reason"] == "geometry_ambiguous"
    else:
        assert coverage["n_matched"] == 1
        assert coverage["lowest"][0]["index"] == 2


@pytest.mark.parametrize("mode,matched", [("polar", 1), ("heavy", 1), ("all", 0)])
def test_coverage_methyl_rotation(tmp_path, capsys, ethanol, mode, matched):
    result = merge(tmp_path, capsys, [ethanol[0]], "--hydrogens", mode)
    path = attempt(tmp_path, ethanol[2], "methyl-rotor")
    assert report(result["output"], [str(path)])["n_matched"] == matched


def test_legacy_json_uses_heavy_and_invalid_mode_is_rejected(tmp_path, capsys, ethanol):
    result = merge(tmp_path, capsys, ethanol[:2], "--rmsd", "0")
    path = Path(result["output"])
    payload = json.loads(path.read_text())
    del payload["hydrogens"]
    path.write_text(json.dumps(payload))
    assert main(["cluster", str(path), "--representative", "medoid", "--rmsd", "0.125", "--json"]) == 0
    clustered = json.loads(capsys.readouterr().out)
    assert clustered["hydrogens"] == "heavy" and len(clustered["representatives"]) == 1
    assert report(path, [])["hydrogens"] == "heavy"
    payload["hydrogens"] = "invalid"
    path.write_text(json.dumps(payload))
    assert main(["cluster", str(path), "--representative", "medoid"]) == 1
    assert "hydrogen mode" in capsys.readouterr().err
    with pytest.raises(ValueError, match="hydrogen mode"):
        report(path, [])


def test_mirror_merge_records_both_rmsds(ethanol):
    first = ethanol[0]
    reflected = replace(first, coordinates=tuple((-x, -y, -z) for x, y, z in first.coordinates))
    frames = [first, reflected]
    records = [geo.record(frame, i, 0) for i, frame in enumerate(frames)]
    reps, _, selected = select(frames, records, 0, 20, 0.125, True,
                               Chem, rdDetermineBonds, rdMolAlign, hydrogens="polar")
    assert len(reps) == 1 and selected == [first]
    member = reps[0]["members"][1]
    assert member["reason"] == "mirror"
    assert member["rmsd"] < 1e-6 and member["heavy_rmsd"] < 1e-6
