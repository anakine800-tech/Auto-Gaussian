"""Synthetic small-molecule geometry tests; no research outputs."""

from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from ag import geometry as g

DATA = Path(__file__).parent / "data" / "butane.xyz"


def test_xyz_roundtrip_and_no_overwrite(tmp_path):
    frames = g.read_xyz(DATA)
    output = tmp_path / "copy.xyz"
    g.write_xyz(output, frames)
    actual = g.read_xyz(output)
    assert [f.coordinates for f in frames] == [f.coordinates for f in actual]
    assert [f.energy for f in actual] == [-157.0, -156.999, -156.999]
    with pytest.raises(FileExistsError):
        g.write_xyz(output, frames)


@pytest.mark.parametrize("contents", ["", "2\nx\nC 0 0 0\n", "1\nx\nC nan 0 0\n",
                                      "-1\nx\n", "1\nx\nC 1 2\n"])
def test_malformed_xyz(tmp_path, contents):
    path = tmp_path / "bad.xyz"
    path.write_text(contents)
    with pytest.raises(ValueError):
        g.read_xyz(path)


def test_symmetry_mirror_and_nonmutation():
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds, rdMolAlign

    frames = g.read_xyz(DATA)
    mols = [g.infer_molecule(f, 0, Chem, rdDetermineBonds) for f in frames]
    assert len({g.graph_key(m, Chem) for m in mols}) == 1
    heavy = [g.heavy_molecule(m, Chem) for m in mols]
    before = Chem.MolToXYZBlock(heavy[1])
    assert g.best_rms(heavy[1], heavy[2], Chem, rdMolAlign) > 0.4
    assert g.best_rms(heavy[1], heavy[2], Chem, rdMolAlign, mirror=True) < 1e-5
    assert Chem.MolToXYZBlock(heavy[1]) == before
    # Reverse atom order: matching must consider chemically equivalent atoms.
    permuted = Chem.RenumberAtoms(heavy[1], list(reversed(range(4))))
    assert g.best_rms(permuted, heavy[1], Chem, rdMolAlign) < 1e-5
    translated = replace(frames[0], coordinates=tuple((y + 3, -x + 2, z + 1)
                                                    for x, y, z in frames[0].coordinates))
    mol = g.heavy_molecule(g.infer_molecule(translated, 0, Chem, rdDetermineBonds), Chem)
    assert g.best_rms(mol, heavy[0], Chem, rdMolAlign) < 1e-5


def test_energy_sources(tmp_path):
    table = tmp_path / "crest.energies"
    table.write_text("1 0.0\n2 0.628\n3 0.628\n")
    frames = g.load_frames([DATA], table)
    assert frames[1].energy == 0.628
    assert frames[1].energy_unit == "kcal/mol"
    table.write_text("-157\n-156.999\n-156.999\n")
    assert g.load_frames([DATA], table)[0].energy_unit == "hartree"
    table.write_text("1 0\n3 1\n2 2\n")
    with pytest.raises(ValueError, match="ordered"):
        g.load_frames([DATA], table)
    table.write_text("1 0\n")
    with pytest.raises(ValueError, match="counts"):
        g.load_frames([DATA], table)
    assert g.comment_energy("conformer 42") == (None, "hartree")
    assert g.comment_energy("energy=-1.2D+02 hartree")[0] == -120


def test_cli_registration_does_not_import_scientific_libraries():
    code = '''
import importlib.abc
import sys
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'rdkit', 'numpy', 'cclib', 'goodvibes'}:
            raise AssertionError('Eager scientific import: ' + fullname)
sys.meta_path.insert(0, Deny())
from ag.cli import main
main([])
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
