"""Offline chemical regressions and study-output CLI checks (no remote operations)."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Molecule strings are probed as possible paths before SMILES interpretation.
pytestmark = pytest.mark.usefixtures('synthetic_cwd')

pytest.importorskip("rdkit")
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

SCRIPTS = Path(__file__).parents[1] / "scripts"
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))
import make_gaussian_input as make
import prepare_conformers as conformers
from cdx_stereo import load_chemdraw_molecules, structure_stereo_invariants

CDX = pytest.mark.skipif(
    not getattr(Chem, "HasChemDrawCDXSupport", lambda: False)(), reason="RDKit lacks ChemDraw CDX support"
)


def run(script, *args, ok=True):
    result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)
    if ok:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert result.returncode != 0, result.stdout
    return result.stderr


def generate(study, source="CCCC", name="screen"):
    return run("prepare_conformers.py", "generate", source, "--study", study, "--name", name,
               "--multiplicity", 1, "--num-conformers", 30)


def frames(path):
    lines = path.read_text().splitlines()
    result = []
    while lines:
        size = int(lines[0])
        result.append((lines[1], lines[2:2 + size]))
        lines = lines[2 + size:]
    return result


@pytest.mark.parametrize("smiles,formula,atoms,cip", [("CCCC", "C4H10", 14, []),
                                                     ("C[C@@H](O)CC", "C4H10O", 15, ["R"])])
def test_smiles_summary(tmp_path, smiles, formula, atoms, cip):
    report = run("prepare_preview.py", smiles, "--study", tmp_path, "--name", "review", "--multiplicity", 1)
    assert report["formula"] == formula
    assert report["explicit_h_atom_count"] == report["atom_count_with_h"] == atoms
    assert report["source_explicit_h_atom_count"] == 0
    assert report["deprecated_fields"] == {"explicit_h_atom_count": "历史字段名，实为补氢后总原子数；请改用 atom_count_with_h"}
    assert [c["cip"] for c in report["chiral_centers"]] == cip
    assert report["charge"] == 0
    assert (tmp_path / "structures/review/preview.png").is_file()


@pytest.mark.parametrize("smiles,error", [("CC(O)CC", "Unassigned tetrahedral"),
                                         ("[CH3]", "Radicals"), ("[Na+]", "Metals"),
                                         ("N->[B-](F)(F)F", "Coordination"), ("C.C", "Disconnected")])
def test_unsupported_structure_stops(tmp_path, smiles, error):
    assert error in run("prepare_preview.py", smiles, "--study", tmp_path, "--name", "bad", "--multiplicity", 1, ok=False)
    assert not (tmp_path / "structures/bad").exists()


def test_multiplicity_not_inferred(tmp_path):
    assert "--multiplicity" in run("prepare_preview.py", "CCCC", "--study", tmp_path, "--name", "review", ok=False)
    assert "--multiplicity" in run("prepare_conformers.py", "generate", "CCCC", "--study", tmp_path, "--name", "screen", ok=False)


@CDX
@pytest.mark.parametrize("fixture,formula,atoms,smiles,cip", [
    ("butane.cdxml", "C4H10", 4, "CCCC", []),
    ("chiral_explicit_h.cdxml", "C4H10O", 6, "[H][C@@](C)(O)CC", ["S"]),
])
def test_chemdraw_identity(tmp_path, fixture, formula, atoms, smiles, cip):
    source = FIXTURES / fixture
    mols, diagnostics = load_chemdraw_molecules(str(source), Chem)
    assert len(mols) == 1
    identity = structure_stereo_invariants(mols[0], Chem, rdMolDescriptors, diagnostics[0])
    assert identity["canonical_isomeric_smiles"] == smiles
    assert identity["formula"] == formula
    assert identity["atom_count"] == atoms
    assert [c["cip"] for c in identity["chiral_centers"]] == cip
    if cip:
        assert identity["explicit_hydrogen_atom_indices"] == [5]
        assert identity["restored_cfg_bond_count"] == 1
    report = run("prepare_preview.py", source, "--study", tmp_path, "--name", "review", "--multiplicity", 1)
    assert report["canonical_isomeric_smiles"] == smiles
    # Also exercise the specialized migrated ChemDraw inspector.
    result = subprocess.run([sys.executable, str(SCRIPTS / "inspect_chemdraw.py"), str(source),
                             "--study", str(tmp_path), "--name", "inspect", "--multiplicity", "1"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    imported = json.loads(next((tmp_path / "structures/inspect").glob("*.json")).read_text())
    assert imported["canonical_isomeric_smiles"] == smiles
    for summary in (report, imported):
        assert summary["explicit_h_atom_count"] == summary["atom_count_with_h"] == (15 if cip else 14)
        assert summary["source_explicit_h_atom_count"] == (1 if cip else 0)
        assert "explicit_h_atom_count" in summary["deprecated_fields"]
    assert all((tmp_path / "structures/inspect" / name).is_file() for name in imported["review_artifacts"].values())
    screen = generate(tmp_path, source)
    assert screen["identity"]["canonical_isomeric_smiles"] == smiles
    assert screen["identity"]["chiral_centers"] == identity["chiral_centers"]


def test_conflicting_cfg_not_repaired(monkeypatch):
    mol = Chem.MolFromSmiles("CC(O)CC")
    bond = mol.GetBondWithIdx(0)
    bond.SetIntProp("_MolFileBondCfg", 1)
    bond.SetBondDir(Chem.BondDir.BEGINDASH)
    monkeypatch.setattr(Chem, "MolsFromCDXMLFile", lambda *args: [mol])
    mols, diagnostics = load_chemdraw_molecules("unused.cdxml", Chem)
    assert diagnostics[0]["conflicting_bond_cfg"]
    assert diagnostics[0]["conflicting_bond_cfg"][0]["existing_direction"] == "BEGINDASH"
    assert diagnostics[0]["restored_bond_cfg"] == []
    with pytest.raises(SystemExit, match="conflicting"):
        make.validate_scope(mols[0], Chem, diagnostics)


def test_multiframe_energy_and_stereo(tmp_path):
    report = generate(tmp_path)
    xyz = frames(tmp_path / "structures/screen/conformers.xyz")
    assert len(xyz) == report["kept_conformers"] > 1
    assert report["force_field"] == "MMFF94s"
    for (comment, rows), candidate in zip(xyz, report["candidates"]):
        assert len(rows) == 14
        assert "MMFF94s kcal/mol" in comment
        assert float(comment.split()[0]) == pytest.approx(candidate["force_field_energy_kcal_mol"])
        assert candidate["relative_force_field_energy_kcal_mol"] <= 6
    chiral = generate(tmp_path, "C[C@@H](O)CC", "chiral")
    original = Chem.AddHs(Chem.MolFromSmiles("C[C@@H](O)CC"))
    for _, rows in frames(tmp_path / "structures/chiral/conformers.xyz"):
        mol = Chem.Mol(original)
        conf = Chem.Conformer(len(rows))
        for i, row in enumerate(rows):
            conf.SetAtomPosition(i, tuple(map(float, row.split()[1:])))
        mol.AddConformer(conf)
        Chem.AssignStereochemistryFrom3D(mol, replaceExistingTags=True)
        centers = Chem.FindMolChiralCenters(mol, useLegacyImplementation=False)
        assert [cip for _, cip in centers] == ["R"]
    assert chiral["identity"]["formula"] == "C4H10O"


def test_boron_uff_fallback(tmp_path):
    report = generate(tmp_path, "CB(O)O")
    assert report["force_field"] == "UFF"
    assert any("UFF fallback" in w for w in report["warnings"])
    assert report["identity"]["formula"] == "CH5BO2"


def test_no_overwrite_or_escape(tmp_path):
    generate(tmp_path)
    path = tmp_path / "structures/screen/conformers.xyz"
    before = path.read_bytes()
    assert "already exists" in run("prepare_conformers.py", "generate", "CCCC", "--study", tmp_path,
                                   "--name", "screen", "--multiplicity", 1, ok=False)
    assert path.read_bytes() == before
    with pytest.raises(SystemExit, match="name must"):
        make.output_directory(tmp_path, "../outside")


def gjf_args(tmp_path, source):
    return [source, "--study", tmp_path, "--name", "input", "--route", "b3lyp/6-31g(d) opt",
            "--charge", 0, "--multiplicity", 1, "--nprocshared", 8, "--mem", "8GB", "--chk", "input.chk"]


def test_xyz_to_gaussian_and_audit(tmp_path):
    generate(tmp_path)
    comment, rows = frames(tmp_path / "structures/screen/conformers.xyz")[0]
    source = tmp_path / "single.xyz"
    source.write_text(f"{len(rows)}\n{comment}\n" + "\n".join(rows) + "\n")
    report = run("make_gaussian_input.py", *gjf_args(tmp_path, source))
    assert report["atom_count"] == 14
    gjf = tmp_path / "structures/input/input.gjf"
    audit = run("audit_cartesian_input.py", gjf)
    assert audit["atom_count"] == 14
    assert audit["element_count"] == {"C": 4, "H": 10}
    assert audit["charge_multiplicity"] == {"charge": 0, "multiplicity": 1}
    assert audit["trailing_blank_line"]
    assert gjf.read_text().startswith("%chk=input.chk\n%mem=8GB\n%nprocshared=8\n#p")
    assert "already exists" in run("make_gaussian_input.py", *gjf_args(tmp_path, source), ok=False)


@pytest.mark.parametrize("option,value,error", [("--chk", "../escape.chk", "chk must"),
                                                 ("--route", "opt\n\n--Link1--", "single line"),
                                                 ("--mem", "8GB\n%chk=bad", "mem must"),
                                                 ("--multiplicity", "3", "closed-shell")])
def test_gaussian_options(tmp_path, option, value, error):
    args = gjf_args(tmp_path, "CCCC")
    args[args.index(option) + 1] = value
    assert error in run("make_gaussian_input.py", *args, ok=False)


def test_reject_multiframe_xyz(tmp_path):
    generate(tmp_path)
    assert "exactly one frame" in run("make_gaussian_input.py", *gjf_args(tmp_path, tmp_path / "structures/screen/conformers.xyz"), ok=False)


def test_formula_and_atom_count_drift_stop(tmp_path, monkeypatch):
    args = SimpleNamespace(source="CCCC", study=tmp_path, name="screen", charge=None, multiplicity=1,
                           num_conformers=10, max_keep=5, energy_window=6, rmsd_threshold=0.5, max_iters=1000, seed=42)
    original = rdMolDescriptors.CalcMolFormula
    monkeypatch.setattr(rdMolDescriptors, "CalcMolFormula", lambda mol: "wrong" if mol.GetNumAtoms() > 4 else original(mol))
    with pytest.raises(SystemExit, match="formula changed"):
        conformers.command_generate(args)
    monkeypatch.setattr(rdMolDescriptors, "CalcMolFormula", original)
    lines = conformers.coordinate_lines
    monkeypatch.setattr(conformers, "coordinate_lines", lambda mol, cid: lines(mol, cid)[:-1])
    with pytest.raises(SystemExit, match="atom count"):
        conformers.command_generate(args)
    assert not (tmp_path / "structures/screen").exists()


@pytest.mark.parametrize("source", ["[H]OC", "[2H]OC", "[H][C@@](C)(O)CC"])
def test_preview_counts_source_h_without_changing_legacy_identity(tmp_path, source):
    legacy, _, diagnostics = make.read_molecule(source, Chem)
    identity = structure_stereo_invariants(legacy, Chem, rdMolDescriptors, diagnostics)
    report = run("prepare_preview.py", source, "--study", tmp_path, "--name", "explicit", "--multiplicity", 1)
    assert report["source_explicit_h_atom_count"] == 1
    assert report["explicit_h_atom_count"] == report["atom_count_with_h"] == Chem.AddHs(legacy).GetNumAtoms()
    assert all(report[key] == value for key, value in identity.items())
