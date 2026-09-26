"""Credential-free local preparation using original Core record APIs."""

from hashlib import sha256
import os
from pathlib import Path
import stat
from uuid import UUID, uuid5

from auto_g16 import core
from auto_g16.core.store import RecordNotFoundError
from auto_g16.execution._program_completion import _validate_material as validate_publisher

from .common import Rejected, RequestRejected, decode_frame, digest, exact, frame
from .material import build_spec, semantic_join, validate_material


class LocalFiles:
    """Pinned local scratch descriptor, exclusive/no-follow evidence writes.

    This is not the deployment filesystem or native durability qualification.
    """
    def __init__(self, root):
        path = Path(root)
        if not path.is_absolute() or ".." in path.parts:
            raise Rejected("MISSING_DEPENDENCY")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def exists(self, intake_id):
        try:
            os.stat(intake_id, dir_fd=self.fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def create(self, material):
        intake_id = material.payload["intake_id"]
        os.mkdir(intake_id, dir_fd=self.fd)
        directory = os.open(intake_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
        identities = [self._identity(os.fstat(directory))]
        try:
            for name, content in (("material.json", material.canonical_payload), ("structure.xyz", material.xyz)):
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                try:
                    offset = 0
                    while offset < len(content):
                        written = os.write(fd, content[offset:])
                        if written <= 0:
                            raise OSError("short write")
                        offset += written
                    identities.append(self._identity(os.fstat(fd)))
                finally:
                    os.close(fd)
        finally:
            os.close(directory)
        return tuple(identities)

    @staticmethod
    def _identity(info):
        return info.st_dev, info.st_ino, info.st_mode

    def check(self, slot):
        directory = os.open(slot.key[2], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            if self._identity(os.fstat(directory)) != slot.files[0]:
                raise Rejected("CONFLICT")
            for n, (name, expected) in enumerate((("material.json", slot.material.canonical_payload), ("structure.xyz", slot.material.xyz)), 1):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or self._identity(info) != slot.files[n] or info.st_size != len(expected):
                        raise Rejected("CONFLICT")
                    chunks, total = [], 0
                    while total <= len(expected):
                        chunk = os.read(fd, min(65536, len(expected) + 1 - total))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                    if b"".join(chunks) != expected:
                        raise Rejected("CONFLICT")
                finally:
                    os.close(fd)
        finally:
            os.close(directory)

    def close(self):
        os.close(self.fd)


class Intake:
    def __init__(self, *, store, registry, scratch, project_id, workflow_run_id, namespace, profile, resources, completion_material, requester_uid):
        if type(requester_uid) is not int or not 1 <= requester_uid <= 4294967294:
            raise Rejected("MISSING_DEPENDENCY")
        self.requester_uid = requester_uid
        self.store, self.registry = store, registry
        self.files = LocalFiles(scratch)
        self.project = store.load_project(project_id)
        self.workflow = store.load_workflow_run(workflow_run_id)
        if self.workflow.project_id != project_id:
            raise Rejected("MISSING_DEPENDENCY")
        self.namespace, self.profile, self.resources = UUID(namespace), profile, dict(resources)
        self._root = registry
        exact(resources, {"tier", "cores", "memory_mb", "walltime_seconds", "queue"})
        if (resources["tier"] != "simple" or type(resources["cores"]) is not int or resources["cores"] != 8
                or type(resources["memory_mb"]) is not int or resources["memory_mb"] != 12288
                or type(resources["walltime_seconds"]) is not int or resources["walltime_seconds"] <= 0
                or not isinstance(resources["queue"], (str, type(None)))):
            raise Rejected("MISSING_DEPENDENCY")
        self.completion_material = completion_material
        self._profile, self._resources_hash = profile, digest(resources)
        self._publisher_hash = digest(completion_material)

    def dependencies(self):
        if self.profile is None or self.completion_material is None:
            raise Rejected("MISSING_DEPENDENCY")
        if self.profile is not self._profile or digest(self.resources) != self._resources_hash or digest(self.completion_material) != self._publisher_hash:
            self._root.lifecycle.poison()
            raise Rejected("CONFLICT")
        validate_publisher(self.completion_material, self.profile)

    def root(self):
        if self.registry is not self._root:
            self._root.lifecycle.poison()
            raise Rejected("LIFECYCLE_BLOCKED")
        self.registry.check()
        return self.registry

    def _records(self, material):
        intake_id = material.payload["intake_id"]
        ids = {role: str(uuid5(self.namespace, intake_id + ":" + role)) for role in ("task", "plan", "resource", "attempt")}
        return (core.Task(task_id=ids["task"], workflow_run_id=self.workflow.workflow_run_id, task_kind="successor-program"),
                core.CalculationPlan(calculation_plan_id=ids["plan"], task_id=ids["task"], revision=1, intent=material.intent),
                core.ResourceSpec(resource_spec_id=ids["resource"], task_id=ids["task"], resources=self.resources),
                core.Attempt(attempt_id=ids["attempt"], task_id=ids["task"], ordinal=1))

    def _owners(self, records):
        names = ("task", "calculation_plan", "resource_spec", "attempt")
        return [(getattr(self.store, "load_" + name), getattr(record, name + "_id"), record) for name, record in zip(names, records)]

    def prepare(self, payload):
        material = validate_material(payload)
        with self._root.lifecycle.composition():
            root = self.root()
            prior = root.index.get(material.payload["intake_id"])
            if prior is not None:
                if prior.material != material:
                    raise Rejected("CONFLICT")
                return self.read_slot(prior)
            self.dependencies()
            spec = build_spec(material, self.profile)
            records = self._records(material)
            semantic_join(material, records[1], spec)
            try:
                if self.files.exists(material.payload["intake_id"]):
                    raise Rejected("CONFLICT")
                for load, record_id, _record in self._owners(records):
                    try:
                        load(record_id)
                    except RecordNotFoundError:
                        continue
                    raise Rejected("CONFLICT")
            except Exception:
                root.lifecycle.poison()
                raise
            slot = root.reserve(material, records, spec)
            try:
                slot.files = self.files.create(material)
                for name, record in zip(("store_task", "store_calculation_plan", "store_resource_spec", "create_attempt"), records):
                    getattr(self.store, name)(record)
                slot.state = "LOCAL_READY"
                return self.read_slot(slot)
            except BaseException:
                slot.state = "INCOMPLETE"
                root.lifecycle.poison()
                raise

    def read_slot(self, slot):
        self.root()
        if slot.state != "LOCAL_READY":
            raise Rejected("INCOMPLETE")
        try:
            self.dependencies()
            self.files.check(slot)
            if self.store.load_project(self.project.project_id) != self.project or self.store.load_workflow_run(self.workflow.workflow_run_id) != self.workflow:
                raise Rejected("STALE")
            for load, record_id, record in self._owners(slot.records):
                if load(record_id) != record:
                    raise Rejected("STALE")
            semantic_join(slot.material, slot.records[1], slot.spec)
        except Exception:
            self._root.lifecycle.poison()
            raise
        task, plan, resource, attempt = slot.records
        return {"intake_id": slot.key[2], "material_sha256": slot.material.identity,
                "input_sha256": sha256(slot.material.xyz).hexdigest(), "input_size_bytes": len(slot.material.xyz),
                "project_id": self.project.project_id, "workflow_run_id": self.workflow.workflow_run_id,
                "task_id": task.task_id, "calculation_plan_id": plan.calculation_plan_id,
                "resource_spec_id": resource.resource_spec_id, "attempt_id": attempt.attempt_id}

    def read(self, intake_id):
        with self._root.lifecycle.composition(readonly=True):
            slot = self.root().index.get(intake_id)
            if slot is None:
                raise RequestRejected("SCOPE")
            return self.read_slot(slot)

    def request(self, raw, *, peer_uid, eof=True, ancillary=False):
        """Offline framing adapter; peer identities must come from native IPC later."""
        operation = None
        try:
            if type(peer_uid) is not int or peer_uid != self.requester_uid:
                raise Rejected("BAD_PEER")
            data = decode_frame(raw, 65536, eof=eof, ancillary=ancillary)
            exact(data, {"protocol", "operation", "payload"})
            if data["protocol"] != "auto-g16-material-prepare/1" or data["operation"] not in ("PREPARE_LOCAL", "READ_LOCAL"):
                raise Rejected("BAD_FRAME")
            operation = data["operation"]
            if operation == "PREPARE_LOCAL":
                result, status = self.prepare(data["payload"]), "PREPARED_LOCAL_ONLY"
            else:
                exact(data["payload"], {"intake_id"})
                result, status = self.read(data["payload"]["intake_id"]), "FOUND_LOCAL"
            reason = "NONE"
        except Rejected as exc:
            status = "INCOMPLETE" if exc.reason == "INCOMPLETE" else "REJECTED"
            # C1 has no SCOPE: an unregistered local bundle is a missing
            # dependency, not a malformed frame. Stale material is a conflict.
            reasons = {
                "BAD_FRAME": "BAD_FRAME", "BAD_PEER": "BAD_PEER",
                "BUSY": "BUSY", "BAD_MATERIAL": "BAD_MATERIAL",
                "CONFLICT": "CONFLICT", "MISSING_DEPENDENCY": "MISSING_DEPENDENCY",
                "STORE_UNAVAILABLE": "STORE_UNAVAILABLE",
                "LIFECYCLE_BLOCKED": "LIFECYCLE_BLOCKED",
                "SCOPE": "MISSING_DEPENDENCY", "STALE": "CONFLICT",
                "INCOMPLETE": "STORE_UNAVAILABLE",
            }
            reason = reasons.get(exc.reason, "STORE_UNAVAILABLE") if isinstance(exc.reason, str) else "STORE_UNAVAILABLE"
            result = None
        except Exception:
            self._root.lifecycle.poison()
            status, reason, result = "UNCERTAIN", "STORE_UNAVAILABLE", None
        return frame({"protocol": "auto-g16-material-prepare/1", "operation": operation,
                      "status": status, "reason": reason, "payload": result}, 65536)
