"""Local descriptor tests use only synthetic small-molecule geometries."""
from dataclasses import replace
import json
import math
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import rdDetermineBonds, rdMolAlign, rdMolTransforms

from ag import geometry as g
from ag.cli import main
from ag.dedup import descriptor_definitions, deduplicate, frame_descriptors

DATA = Path(__file__).parent / "data" / "butane.xyz"


def at_angle(angle):
    frame = g.read_xyz(DATA)[0]
    mol = g.infer_molecule(frame, 0, Chem, rdDetermineBonds)
    rdMolTransforms.SetDihedralDeg(mol.GetConformer(), 0, 1, 2, 3, angle)
    return replace(frame, coordinates=tuple(map(tuple, mol.GetConformer().GetPositions())))


def run_dedup(frames, definitions=None, **kwargs):
    pairs = []
    kept, excluded, selected = deduplicate(
        frames, 0, kwargs.pop("rmsd", 1.0), kwargs.pop("de", 0.05), kwargs.pop("window", 3.0),
        Chem, rdDetermineBonds, rdMolAlign, descriptors=definitions, kept_by_bins=pairs, **kwargs)
    return kept, excluded, selected, pairs


@pytest.mark.parametrize("angle", [-179, -120, -90, -60, -10, 0, 10, 60, 90, 120, 179])
def test_signed_dihedral_matches_independent_rdkit(angle):
    frame = at_angle(angle)
    assert g.dihedral(frame.coordinates, [1, 2, 3, 4]) == pytest.approx(angle)
    shifted = tuple((z + 2, x - 4, y + 1) for x, y, z in frame.coordinates)
    assert g.dihedral(shifted, [1, 2, 3, 4]) == pytest.approx(angle)


@pytest.mark.parametrize("left,right,expected", [(350, 10, 20), (179, -179, 2),
                                                  (0, 180, 180), (720, 0, 0)])
def test_periodic_difference(left, right, expected):
    assert g.periodic_difference(left, right) == expected
    assert g.periodic_difference(right, left) == expected


@pytest.mark.parametrize("angle,expected", [(-180, 3), (180, 3), (-60, 1),
                                           (60, 2), (0, 1), (120, 2), (-120, 3)])
def test_exact_boundaries_start_half_open_bin(angle, expected):
    assert g.dihedral_bin(angle, [-60, 60, 180]) == expected
    assert g.dihedral_bin(angle, [-90]) == 1


def test_gauche_bins_prevent_merge_and_preserve_coordinates():
    frames = [at_angle(60), at_angle(-60)]
    before = g.xyz_text(frames)
    assert len(run_dedup(frames)[0]) == 1
    defs = descriptor_definitions(["1,2,3,4:-120,0,120@gauche-,gauche+,anti"])
    kept, excluded, selected, pairs = run_dedup(frames, defs)
    assert [r["bins"] for r in kept] == [[2], [1]]
    assert not excluded and selected == frames
    assert g.xyz_text(frames) == before
    assert len(pairs) == 1
    assert pairs[0]["indices"] == [1, 2]
    assert pairs[0]["bins"] == [[2], [1]]
    assert 0 < pairs[0]["rmsd"] < 1
    assert not run_dedup(frames, defs, rmsd=0.01)[3]


def test_wrap_bin_and_merged_periodic_difference():
    defs = descriptor_definitions(["1,2,3,4:-90,90@s-cis,s-trans"])
    kept, excluded, _, pairs = run_dedup([at_angle(179), at_angle(-179)], defs)
    assert len(kept) == len(excluded) == 1 and not pairs
    assert kept[0]["bins"] == excluded[0]["bins"] == [2]
    assert excluded[0]["max_periodic_dihedral_difference"] == pytest.approx(2)
    assert not kept[0]["near_boundary"]
    _, excluded, _, _ = run_dedup([at_angle(350), at_angle(10)], defs)
    assert excluded[0]["max_periodic_dihedral_difference"] == pytest.approx(20)


@pytest.mark.parametrize("angle,near,group", [(86, True, 1), (94, True, 2),
                                             (-86, True, 1), (-94, True, 2),
                                             (84, False, 1), (96, False, 2)])
def test_near_boundary_is_warning_only(angle, near, group):
    defs = descriptor_definitions(["1,2,3,4:-90,90"])
    result = frame_descriptors(at_angle(angle), defs, 0)
    assert result["near_boundary"] is near
    assert result["bins"] == [group]


def test_near_boundary_strict_five_degrees(monkeypatch):
    defs = descriptor_definitions(["1,2,3,4:-90,90"])
    monkeypatch.setattr(g, "dihedral", lambda *args: 85.0)
    assert not frame_descriptors(at_angle(85), defs, 0)["near_boundary"]


def test_multiple_rotors_combine_and_maximum_is_over_all_dihedrals():
    from rdkit.Chem import AllChem
    mol = Chem.AddHs(Chem.MolFromSmiles("CCCCC"))
    assert AllChem.EmbedMolecule(mol, randomSeed=23) == 0
    frames = []
    for left, right in [(170, 60), (175, -60), (179, 70)]:
        conf = mol.GetConformer()
        rdMolTransforms.SetDihedralDeg(conf, 0, 1, 2, 3, left)
        rdMolTransforms.SetDihedralDeg(conf, 1, 2, 3, 4, right)
        frames.append(g.Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()),
                              tuple(map(tuple, conf.GetPositions())), energy=-10))
    defs = descriptor_definitions(["1,2,3,4:-90,90@cis,trans", "2,3,4,5:-120,0,120"])
    kept, excluded, _, pairs = run_dedup(frames, defs)
    assert [r["bins"] for r in kept] == [[2, 2], [2, 1]]
    assert excluded[0]["index"] == 3
    assert excluded[0]["representative"] == 1
    assert excluded[0]["max_periodic_dihedral_difference"] == pytest.approx(10)
    assert len(pairs) == 1


def test_same_bin_still_requires_energy_and_rmsd_thresholds():
    defs = descriptor_definitions(["1,2,3,4:-90,90"])
    frames = [at_angle(100), at_angle(150)]
    assert len(run_dedup(frames, defs, rmsd=0.001)[0]) == 2
    frames = [at_angle(179), replace(at_angle(-179), energy=-156.999)]
    assert len(run_dedup(frames, defs)[0]) == 2
    assert not run_dedup(frames, defs)[3]
    frames = [at_angle(60), replace(at_angle(-60), energy=-156.0)]
    kept, excluded, _, pairs = run_dedup(frames, defs)
    assert len(kept) == 1 and excluded[0]["reason"] == "energy_window" and not pairs


def test_distances_and_contacts_independent_and_report_only():
    defs = descriptor_definitions(report_distance=["1,4", "2,3"], contact_atoms=["1,2", "2,4"])
    assert defs["contact_atoms"] == [1, 2, 4] and defs["contact_cutoff"] == 3
    frames = [at_angle(60), at_angle(-60)]
    kept, excluded, _, pairs = run_dedup(frames, defs)
    assert len(kept) == len(excluded) == 1 and not pairs
    for frame, row in zip(frames, [kept[0], excluded[0]]):
        def distance(i, j):
            return math.sqrt(sum((x - y) ** 2 for x, y in
                                 zip(frame.coordinates[i - 1], frame.coordinates[j - 1])))
        assert row["distances"] == pytest.approx([distance(1, 4), distance(2, 3)])
        expected = [[i, j] for i in range(1, 15) for j in range(i + 1, 15)
                    if (i in [1, 2, 4] or j in [1, 2, 4]) and distance(i, j) < 3]
        assert row["contacts"] == expected
        assert row["dihedrals"] == row["bins"] == [] and not row["near_boundary"]
    assert excluded[0]["max_periodic_dihedral_difference"] is None
    assert g.contact_fingerprint(((0, 0, 0), (3, 0, 0), (0, 2, 0)), [1, 3], 3) == [[1, 3]]


@pytest.mark.parametrize("spec", ["1,2,3:-90,90", "1,2,2,4:-90,90", "0,2,3,4:-90,90",
    "1,2,3,4", "1,2,3,4:", "1,2,3,4:90,-90", "1,2,3,4:-181,90", "1,2,3,4:-180,180",
    "1,2,3,4:0,0", "1,2,3,4:nan,90", "1,2,3,4:-90,inf", "1,2,3,4:-90,90@cis",
    "1,2,3,4:-90,90@cis,", "1,2,3,4:-90,90@cis,cis", "1,2,3,4:-90,90@a,b@c"])
def test_bad_dihedral_definitions_identify_option(spec):
    with pytest.raises(ValueError, match="--dihedral-bins"):
        descriptor_definitions([spec])


@pytest.mark.parametrize("kwargs", [dict(report_distance=["1"]), dict(report_distance=["1,1"]),
    dict(contact_atoms=["0,2"]), dict(contact_atoms=["a"]), dict(contact_atoms=["1," ]),
    dict(contact_atoms=["1"], contact_cutoff=-1), dict(contact_atoms=["1"], contact_cutoff=float("nan")),
    dict(contact_cutoff=2)])
def test_bad_distance_contact_options(kwargs):
    with pytest.raises(ValueError):
        descriptor_definitions(**kwargs)


@pytest.mark.parametrize("kwargs,label", [(dict(dihedral_bins=["1,2,3,15:-90,90"]), "dihedral"),
    (dict(report_distance=["1,15"]), "distance"), (dict(contact_atoms=["15"]), "contact atoms")])
def test_out_of_range_fails_before_output(tmp_path, capsys, kwargs, label):
    option, values = next(iter(kwargs.items()))
    cli_args = ["--" + option.replace("_", "-"), values[0]]
    assert main(["dedup", str(DATA), "--charge", "0", "--out", str(tmp_path), *cli_args]) == 1
    error = capsys.readouterr().err
    assert "frame 1" in error and label in error and "15" in error and "out of range" in error
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("coincident", [False, True])
def test_undefined_dihedral_even_outside_energy_window(coincident):
    frame = at_angle(60)
    coordinates = list(frame.coordinates)
    coordinates[:4] = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)]
    if coincident:
        coordinates[2] = coordinates[1]
    broken = replace(frame, coordinates=tuple(coordinates), energy=100)
    defs = descriptor_definitions(["1,2,3,4:-90,90"])
    with pytest.raises(ValueError, match=r"frame 2, dihedral \[1, 2, 3, 4\]: undefined"):
        run_dedup([frame, broken], defs)


@pytest.mark.parametrize("source_mode", [None, "first", "lowest"])
def test_cli_descriptors_and_source_members(tmp_path, capsys, source_mode):
    a, b = tmp_path / "a.xyz", tmp_path / "b.xyz"
    g.write_xyz(a, [at_angle(60)])
    g.write_xyz(b, [at_angle(-60), at_angle(62)])
    inputs = [str(a), str(b)] if source_mode is None else ["--source", f"A={a}", "--source", f"B={b}"]
    if source_mode == "lowest":
        inputs += ["--representative", "lowest"]
    args = ["dedup", *inputs, "--charge", "0", "--rmsd", "1", "--out", str(tmp_path), "--json",
            "--dihedral-bins", "1,2,3,4:-120,0,120@minus,plus,anti",
            "--dihedral-bins", "1,2,3,4:-90,90", "--report-distance", "1,4",
            "--report-distance", "2,3", "--contact-atoms", "1", "--contact-atoms", "2,4",
            "--contact-cutoff", "2.5"]
    assert main(args) == 0
    output = json.loads(capsys.readouterr().out)
    saved = json.loads(Path(output.pop("output")).read_text())
    assert saved == output
    assert len(output["kept"]) == 2 and len(output["excluded"]) == 1
    assert output["excluded"][0]["max_periodic_dihedral_difference"] == pytest.approx(2, abs=1e-7)
    assert output["descriptors"]["dihedral_bins"][0]["names"] == ["minus", "plus", "anti"]
    assert output["descriptors"]["dihedral_bins"][1]["names"] == ["bin1", "bin2"]
    assert output["descriptors"]["contact_cutoff"] == 2.5
    assert output["kept_by_bins"][0]["indices"] == [1, 2]
    assert output["kept_by_bins"][0]["bins"] == [[2, 1], [1, 1]]
    if source_mode:
        representative = output["kept"][0]
        assert representative["sources"] == ["A", "B"]
        assert [m["bins"] for m in representative["members"]] == [[2, 1], [2, 1]]
        assert representative["members"][1]["max_periodic_dihedral_difference"] == pytest.approx(2, abs=1e-7)
        assert output["kept"][1]["sources"] == ["B"]


def test_boundary_warning_wraps_at_180():
    defs = descriptor_definitions(["1,2,3,4:-60,60,180"])
    rows = [frame_descriptors(at_angle(angle), defs, 0) for angle in (179, -179)]
    assert all(row["near_boundary"] for row in rows)
    assert [row["bins"] for row in rows] == [[2], [3]]


def test_source_lowest_energy_ranking_and_window_survive_bins():
    defs = descriptor_definitions(["1,2,3,4:-120,0,120"])
    frames = [at_angle(60), replace(at_angle(-60), energy=-157.00001),
              replace(at_angle(62), energy=-157.00002), replace(at_angle(180), energy=-156)]
    kept, excluded, _, pairs = run_dedup(frames, defs, routes=["A", "B", "B", "C"],
                                        representative="lowest")
    assert [r["index"] for r in kept] == [3, 2]
    duplicate = next(r for r in excluded if r["reason"] == "duplicate")
    assert duplicate["index"] == 1 and duplicate["representative"] == 3
    assert duplicate["max_periodic_dihedral_difference"] == pytest.approx(2)
    assert next(r for r in excluded if r["reason"] == "energy_window")["index"] == 4
    assert pairs[0]["indices"] == [3, 2]
