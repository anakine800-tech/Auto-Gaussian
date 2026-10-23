"""T109 regression cases: synthetic small molecules, never research structures."""

from dataclasses import replace
import json
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdDetermineBonds, rdMolAlign, rdMolTransforms

from ag import geometry as g
from ag.cli import main
from ag.cluster import select
from ag.dedup import deduplicate

DATA = Path(__file__).parent / "data" / "butane.xyz"


def molecule(smiles):
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    assert AllChem.EmbedMolecule(mol, randomSeed=109) == 0
    AllChem.MMFFOptimizeMolecule(mol)
    return mol


def frame(mol):
    return g.Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()),
                   tuple(map(tuple, mol.GetConformer().GetPositions())), energy=-100.0)


def dedup(frames, **kwargs):
    report = {}
    result = deduplicate(frames, 0, kwargs.pop("rmsd", 0.125), kwargs.pop("de", 0.05), 3.0,
                         Chem, rdDetermineBonds, rdMolAlign, report=report, **kwargs)
    return (*result, report)


@pytest.fixture
def ring_flip():
    first = molecule("CCCc1ccccc1")
    rotated = Chem.Mol(first)
    conf = rotated.GetConformer()
    angle = rdMolTransforms.GetDihedralDeg(conf, 1, 2, 3, 4)
    rdMolTransforms.SetDihedralDeg(conf, 1, 2, 3, 4, angle + 180)
    return first, rotated


@pytest.mark.parametrize("hydrogens", ["heavy", "polar", "all"])
def test_ring_flip_and_kekule_representation(ring_flip, hydrogens):
    first, rotated = ring_flip
    frames = list(map(frame, ring_flip))
    before = [Chem.MolToMolBlock(m) for m in ring_flip]
    kept, excluded, selected, _ = dedup(frames, hydrogens=hydrogens)
    assert len(kept) == len(excluded) == 1
    assert excluded[0]["mapping"] == "symmetry"
    assert excluded[0]["rmsd"] < 0.02
    assert selected == frames[:1]
    # Explicitly retain Kekule bonds to expose the old automatic mapper's miss.
    localized = [Chem.Mol(m) for m in ring_flip]
    for mol in localized:
        Chem.Kekulize(mol, clearAromaticFlags=True)
    left, right = [g.rms_molecule(m, Chem, hydrogens) for m in localized]
    assert rdMolAlign.GetBestRMS(Chem.Mol(left), right) > 1.0
    rmsd, mapping = g.best_rms(left, right, Chem, rdMolAlign, return_mapping=True)
    assert rmsd < 0.02 and mapping == "symmetry"
    # Opposite Kekule assignment must give exactly the same geometric result.
    for bond in localized[1].GetBonds():
        if bond.IsInRing():
            bond.SetBondType(Chem.BondType.SINGLE if bond.GetBondType() == Chem.BondType.DOUBLE
                             else Chem.BondType.DOUBLE)
    alternate = g.rms_molecule(localized[1], Chem, hydrogens)
    assert g.best_rms(left, alternate, Chem, rdMolAlign) == pytest.approx(rmsd, abs=1e-7)
    assert [Chem.MolToMolBlock(m) for m in ring_flip] == before
    # cluster's direct comparison inherits the same mapping improvement.
    records = [g.record(f, i, 0) for i, f in enumerate(frames)]
    reps, excluded, _ = select(frames, records, 0, 20, 0.125, False,
                               Chem, rdDetermineBonds, rdMolAlign, hydrogens=hydrogens)
    assert len(reps) == 1 and not excluded


def test_identity_and_distinct_conformers():
    frames = g.read_xyz(DATA)
    same = replace(frames[0], coordinates=tuple((y + 3, -x + 2, z + 1)
                                               for x, y, z in frames[0].coordinates))
    kept, excluded, selected, _ = dedup([*frames, same])
    assert [r["index"] for r in kept] == [1, 2, 3]
    assert excluded[0]["mapping"] == "identity"
    assert excluded[0]["rmsd"] < 1e-6
    assert selected == frames


def test_odd_permutation_at_stereocenter_is_rejected():
    # Ethyl/vinyl become topology-equivalent when bond order is ignored.
    mol = g.rms_molecule(molecule("C[C@H](CC)C=C"), Chem, "heavy")
    forbidden = [(0, 0), (1, 1), (2, 4), (3, 5), (4, 2), (5, 3)]
    assert forbidden not in g.rms_atom_maps(mol, mol, Chem)
    swapped = Chem.Mol(mol)
    for i, j in forbidden:
        swapped.GetConformer().SetAtomPosition(i, mol.GetConformer().GetAtomPosition(j))
    unsafe = rdMolAlign.GetBestRMS(Chem.Mol(swapped), mol, map=[forbidden])
    assert unsafe < 1e-6
    assert g.best_rms(swapped, mol, Chem, rdMolAlign) > 0.1
    achiral = Chem.Mol(mol)
    Chem.RemoveStereochemistry(achiral)
    assert forbidden in g.rms_atom_maps(achiral, achiral, Chem)


@pytest.mark.parametrize("mode", ["heavy", "polar", "all"])
def test_stereo_preserving_reindexing_after_hydrogen_projection(mode):
    mol = molecule("C[C@H](O)CC")
    other = Chem.RenumberAtoms(mol, list(reversed(range(mol.GetNumAtoms()))))
    left, right = [g.rms_molecule(m, Chem, mode) for m in (mol, other)]
    assert g.best_rms(left, right, Chem, rdMolAlign) < 1e-6


def test_mapping_cap_checks_one_beyond_limit_even_for_identity(monkeypatch, tmp_path, capsys):
    mol = molecule("C")  # 24 all-H mappings, no truncation accepted even at RMSD 0.
    monkeypatch.setattr(g, "RMS_MAX_MAPPINGS", 24)
    assert len(g.rms_atom_maps(mol, mol, Chem)) == 24
    monkeypatch.setattr(g, "RMS_MAX_MAPPINGS", 23)
    with pytest.raises(ValueError, match="exceed 23.*--hydrogens heavy"):
        g.best_rms(mol, mol, Chem, rdMolAlign)
    path = tmp_path / "methane.xyz"
    g.write_xyz(path, [frame(mol)] * 2)
    output = tmp_path / "results"
    assert main(["dedup", str(path), "--hydrogens", "all", "--charge", "0",
                 "--out", str(output)]) == 1
    assert "--hydrogens heavy" in capsys.readouterr().err
    assert not output.exists()
    assert main(["dedup", str(path), "--hydrogens", "heavy", "--charge", "0",
                 "--out", str(output)]) == 0


def test_mirror_report_never_merges_and_default_is_off(tmp_path, capsys):
    base = ["dedup", str(DATA), "--charge", "0", "--out", str(tmp_path), "--json"]
    results = []
    for options in ([], ["--mirror", "off"], ["--mirror", "report"]):
        assert main([*base, *options]) == 0
        result = json.loads(capsys.readouterr().out)
        xyz = Path(result["output"]).with_suffix(".xyz").read_bytes()
        result.pop("output")
        result.pop("xyz_file")
        results.append((result, xyz))
    assert results[0] == results[1]
    off, reported = results[0][0], results[2][0]
    assert "mirror_pairs" not in off
    assert reported["kept"] == off["kept"] and reported["excluded"] == off["excluded"]
    assert results[0][1] == results[2][1]
    assert len(reported["mirror_pairs"]) == 1
    pair = reported["mirror_pairs"][0]
    assert pair["indices"] == [2, 3]
    assert pair["rmsd"] > 0.4 and pair["mirror_rmsd"] < 1e-5
    assert pair["delta_energy_kcal"] == 0
    assert pair["mapping"] in {"identity", "symmetry"}
    assert pair["mirror_mapping"] in {"identity", "symmetry"}
    with pytest.raises(SystemExit):
        main([*base, "--mirror", "merge"])


def test_chiral_report_keeps_stereo_exclusion_and_warns():
    first = frame(molecule("C[C@H](O)CC"))
    opposite = replace(first, coordinates=tuple((-x, -y, -z) for x, y, z in first.coordinates))
    # Different energies retain both same-stereoisomer frames. A loose reporting
    # threshold exercises a chiral mirror candidate; it is not an enantiomer claim.
    higher = replace(first, energy=first.energy + 0.1 / g.HARTREE_TO_KCAL)
    off = dedup([first, higher, opposite], rmsd=2)
    reported = dedup([first, higher, opposite], rmsd=2, mirror="report")
    assert off[:3] == reported[:3]
    assert len(reported[0]) == 2
    assert reported[1][0]["reason"] == "stereo_changed"
    assert len(reported[3]["mirror_pairs"]) == 1
    assert "手性体系，镜像对不是同一构象，仅供识别对映构象" in reported[3]["mirror_note"]


def torsion(angle):
    first = g.read_xyz(DATA)[0]
    mol = g.infer_molecule(first, 0, Chem, rdDetermineBonds)
    rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 0, 1, 2, 3, angle)
    return replace(first, coordinates=tuple(map(tuple, mol.GetConformer().GetPositions())))


def test_boundary_pairs_and_greedy_order_dependence():
    frames = [torsion(a) for a in (80, 100, 120)]
    left = dedup(frames, rmsd=0.125)
    middle = dedup([frames[1], frames[0], frames[2]], rmsd=0.125)
    assert len(left[0]) == 2 and len(middle[0]) == 1
    assert left[3]["algorithm"]["order_dependent"] is True
    assert left[3]["algorithm"]["ordering"] == "energy_ascending_then_input_order"
    pairs = left[3]["boundary_pairs"]
    assert {p["kind"] for p in pairs} == {"merged", "representatives"}
    for pair in pairs:
        assert pair["delta_energy_kcal"] == 0
        assert pair["mapping"] in {"identity", "symmetry"}
        assert (0.0625 < pair["rmsd"] < 0.125 if pair["kind"] == "merged" else
                0.125 <= pair["rmsd"] < 0.25)


def test_boundary_strict_limits_and_incomparable_energy():
    frames = [torsion(80), torsion(100)]
    mols = [g.rms_molecule(g.infer_molecule(f, 0, Chem, rdDetermineBonds), Chem, "polar")
            for f in frames]
    distance = g.best_rms(mols[1], mols[0], Chem, rdMolAlign)
    assert dedup(frames, rmsd=distance / 2)[3]["boundary_pairs"] == []
    assert dedup(frames, rmsd=distance * 2)[3]["boundary_pairs"] == []
    assert len(dedup(frames, rmsd=distance)[3]["boundary_pairs"]) == 1
    frames[1] = replace(frames[1], energy=30, energy_unit="kcal/mol")
    result = dedup(frames, routes=["crest", "mdopt"], rmsd=0.1)
    assert result[3]["algorithm"]["ordering"] == "input_order"
    assert result[3]["boundary_pairs"][0]["delta_energy_kcal"] is None
