from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from unittest.mock import patch

from auto_g16 import core
from auto_g16._managed_offline.common import Rejected, decode_frame, frame
from auto_g16._managed_offline.material import decode_xyz, encode_xyz, semantic_join, validate_material
from ._fixtures import Fixture, payload


class MaterialTests(Fixture):
    def test_read_local_unregistered_uuid_uses_closed_missing_dependency_reason(self):
        raw = frame({"protocol": "auto-g16-material-prepare/1", "operation": "READ_LOCAL",
                     "payload": {"intake_id": payload()["intake_id"]}}, 65536)
        result = decode_frame(self.intake.request(raw, peer_uid=501), 65536, eof=True)
        self.assertEqual((result["status"], result["reason"], result["payload"]),
                         ("REJECTED", "MISSING_DEPENDENCY", None))
        self.assertEqual(self.life.state, "READY_CLOSED")
        self.assertEqual(self.registry.allocated_count, 0)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(self.native.shapes, [])
        self.assertEqual(list((self.root / "intake").iterdir()), [])

    def test_material_internal_rejections_never_extend_wire_reason_enum(self):
        allowed = {"NONE", "BAD_FRAME", "BAD_PEER", "BUSY", "BAD_MATERIAL", "CONFLICT",
                   "MISSING_DEPENDENCY", "STORE_UNAVAILABLE", "LIFECYCLE_BLOCKED"}
        raw = frame({"protocol": "auto-g16-material-prepare/1", "operation": "READ_LOCAL",
                     "payload": {"intake_id": payload()["intake_id"]}}, 65536)
        cases = [(x, x) for x in sorted(allowed - {"NONE"})]
        cases += [("SCOPE", "MISSING_DEPENDENCY"), ("STALE", "CONFLICT"),
                  ("INCOMPLETE", "STORE_UNAVAILABLE"), ("UNKNOWN_INTERNAL", "STORE_UNAVAILABLE"),
                  ("NONE", "STORE_UNAVAILABLE"), (None, "STORE_UNAVAILABLE"), ([], "STORE_UNAVAILABLE")]
        self.life.poison()
        for internal, expected in cases:
            with self.subTest(internal=internal), patch.object(self.intake, "read", side_effect=Rejected(internal)) as read:
                result = decode_frame(self.intake.request(raw, peer_uid=501), 65536, eof=True)
                self.assertIn(result["reason"], allowed)
                self.assertEqual(result["reason"], expected)
                self.assertEqual(result["status"], "INCOMPLETE" if internal == "INCOMPLETE" else "REJECTED")
                self.assertIsNone(result["payload"])
                read.assert_called_once()
                self.assertEqual(self.life.state, "BLOCKED")
        self.assertEqual(self.registry.allocated_count, 0)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(self.native.shapes, [])

    def test_missing_publisher_dependency_rejects_before_local_writes(self):
        self.intake.completion_material = None
        with self.assertRaisesRegex(Rejected, "MISSING_DEPENDENCY"):
            self.intake.prepare(payload())
        self.assertEqual(self.registry.allocated_count, 0)
        self.assertEqual(list((self.root / "intake").iterdir()), [])

    def test_resource_policy_drift_poison_before_new_material(self):
        self.intake.resources["cores"] = 22
        with self.assertRaises(Rejected):
            self.intake.prepare(payload())
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertEqual(self.registry.allocated_count, 0)

    def test_integer_roundtrip_no_float_and_complete_semantic_join(self):
        p = payload()
        p["atoms"][0].update(x_microangstrom=-1, y_microangstrom=1000000000, z_microangstrom=-1000000000)
        material = validate_material(p)
        self.assertIn(b"H -0.000001 1000.000000 -1000.000000\n", material.xyz)
        self.assertEqual(decode_xyz(material.xyz), p["atoms"])
        result = self.intake.prepare(p)
        slot = self.registry.index[p["intake_id"]]
        self.assertEqual(result["input_sha256"], sha256(material.xyz).hexdigest())
        semantic_join(slot.material, slot.records[1], slot.spec)
        self.assertEqual(self.core.attempt_state(slot.records[3].attempt_id), core.AttemptState.PLANNED)
        self.assertEqual(self.approvals.evidence_count(), 0)
        self.assertEqual(self.native.shapes, [])

    def test_typed_rejections_before_reservation_or_core_write(self):
        valid = payload()
        variants = []
        for key, bad in (("schema", "wrong"), ("intake_id", "../x"), ("model", None), ("model", "gfn0"),
                         ("charge", False), ("charge", 1), ("multiplicity", True), ("multiplicity", 3),
                         ("unpaired_electrons", 1), ("solvent", "water"), ("task", "optimize"),
                         ("structure_identity", "x\ny"), ("stereochemistry_review", ""), ("structure_identity", "e\u0301"),
                         ("atoms", []), ("atoms", valid["atoms"] * 65)):
            variants.append({**valid, key: bad})
        for key in valid:
            variants.append({k: v for k, v in valid.items() if k != key})
        for key in ("argv", "profile", "path", "raw_xyz", "ProgramSpec", "approved"):
            variants.append({**valid, key: "not allowed"})
        for bad in (True, 0.1, float("nan"), float("inf"), 1000000001):
            p = deepcopy(valid)
            p["atoms"][0]["x_microangstrom"] = bad
            variants.append(p)
        for element in ("Fe", "X", "h", None):
            p = deepcopy(valid)
            p["atoms"][0]["element"] = element
            variants.append(p)
        variants.extend([{**valid, "atoms": [valid["atoms"][0]]}, {**valid, "atoms": [valid["atoms"][0]] * 2}])
        with patch.object(self.core, "store_task", wraps=self.core.store_task) as writer:
            for p in variants:
                with self.subTest(p=p), self.assertRaises(Rejected):
                    self.intake.prepare(p)
            writer.assert_not_called()
        self.assertEqual(self.registry.allocated_count, 0)
        self.assertEqual(list((self.root / "intake").iterdir()), [])

    def test_semantic_join_rejects_plan_or_spec_or_input_splice(self):
        a, b = self.make(model="gfn1"), self.make(model="gfn2")
        for material, plan, spec in ((a.material, a.records[1], b.spec), (a.material, b.records[1], a.spec),
                                      (b.material, a.records[1], a.spec),
                                      (replace(a.material, xyz=a.material.xyz + b"\n"), a.records[1], a.spec)):
            with self.assertRaises(Rejected):
                semantic_join(material, plan, spec)

    def test_repeated_intake_read_only_no_second_attempt_or_overwrite(self):
        p = payload()
        first = self.intake.prepare(p)
        with patch.object(self.core, "create_attempt", side_effect=AssertionError("no second Attempt")):
            self.assertEqual(self.intake.prepare(p), first)
            self.assertEqual(self.intake.read(p["intake_id"]), first)
            with self.assertRaises(Rejected):
                self.intake.prepare({**p, "model": "gfn1"})
        self.assertEqual(self.registry.allocated_count, 1)

    def test_partial_write_keeps_slot_and_read_only_incomplete(self):
        p = payload()
        with patch.object(self.core, "store_resource_spec", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                self.intake.prepare(p)
        self.assertEqual(self.registry.allocated_count, 1)
        self.assertEqual(self.life.state, "BLOCKED")
        slot = self.registry.index[p["intake_id"]]
        self.assertEqual(slot.state, "INCOMPLETE")
        self.assertEqual(self.core.load_calculation_plan(slot.records[1].calculation_plan_id), slot.records[1])
        with self.assertRaisesRegex(Rejected, "INCOMPLETE"):
            self.intake.read(p["intake_id"])
        with patch.object(self.core, "create_attempt", side_effect=AssertionError("no repair")):
            with self.assertRaises(Rejected):
                self.intake.prepare(p)

    def test_orphan_local_target_blocks_before_reservation(self):
        p = payload()
        (self.root / "intake" / p["intake_id"]).mkdir()
        with self.assertRaises(Rejected):
            self.intake.prepare(p)
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertEqual(self.registry.allocated_count, 0)

    def test_orphan_core_target_blocks_without_recognizing_new_bundle(self):
        p = payload()
        records = self.intake._records(validate_material(p))
        self.core.store_task(records[0])
        with self.assertRaises(Rejected):
            self.intake.prepare(p)
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertEqual(self.registry.allocated_count, 0)

    def test_material_file_loss_blocks_no_repair(self):
        slot = self.make()
        # Rename retained evidence within task scratch; no deletion/truncation.
        original = self.root / "intake" / slot.key[2] / "structure.xyz"
        original.rename(original.with_name("retained.xyz"))
        with self.assertRaises(FileNotFoundError):
            self.intake.read(slot.key[2])
        self.assertEqual(self.life.state, "BLOCKED")
        self.assertFalse(original.exists())

    def test_dependency_missing_and_material_frame_boundary(self):
        self.intake.profile = None
        raw = frame({"protocol": "auto-g16-material-prepare/1", "operation": "PREPARE_LOCAL", "payload": payload()}, 65536)
        result = decode_frame(self.intake.request(raw, peer_uid=501), 65536, eof=True)
        self.assertEqual(result["reason"], "MISSING_DEPENDENCY")
        self.assertEqual(self.registry.allocated_count, 0)
        for opts in ({"eof": False}, {"ancillary": True}, {"peer_uid": 502}):
            result = decode_frame(self.intake.request(raw, **{"peer_uid": 501, **opts}), 65536, eof=True)
            self.assertEqual(result["status"], "REJECTED")

    def test_xyz_canonical_parser_rejects_negative_zero_extra_rows_and_precision(self):
        original = encode_xyz(payload()["atoms"])
        for raw in (original.replace(b"0.000000", b"-0.000000", 1), original + b"\n",
                    original.replace(b"0.740000", b"0.74"), original.replace(b"2\n", b"02\n", 1)):
            with self.assertRaises(Rejected):
                decode_xyz(raw)
