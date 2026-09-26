"""Finite lifetime associations, never durable approval or execution authority."""

from dataclasses import dataclass, field
from uuid import uuid4

from .common import Rejected, digest

GATES = ("scientific", "batch", "operational")
CAPACITY = 1024
MAX_GENERATION = (1 << 64) - 1


@dataclass
class Cell:
    subject: str | None
    state: str = "UNPREPARED"
    generation: int = 0
    view_id: str | None = None
    event_id: str | None = None
    view_hash: str | None = None
    ids: tuple = ()
    hashes: tuple = ()
    selected: str | None = None
    selected_id: str | None = None


@dataclass
class Slot:
    ordinal: int
    key: tuple
    c: object
    material: object
    records: tuple
    spec: object
    state: str = "RESERVED"
    snapshot: object = None
    cells: dict = field(default_factory=dict)
    files: tuple = ()

    def __post_init__(self):
        self.cells = {"scientific": Cell(self.records[1].calculation_plan_id),
                      "batch": Cell(self.key[2]), "operational": Cell(None)}
        self._cells = tuple(self.cells[g] for g in GATES)
        self._identity = self.identity()
        self._snapshot = None

    def identity(self):
        return (self.ordinal, self.key, id(self.c), self.material.identity,
                tuple(self.records), self.spec.program_execution_spec_id)


class Registry:
    def __init__(self, lifecycle, installation_hash):
        if lifecycle.state != "READY_CLOSED" or lifecycle._registry_created:
            raise Rejected("LIFECYCLE_BLOCKED")
        lifecycle._registry_created = True
        self.lifecycle, self.installation_hash = lifecycle, installation_hash
        self.lifetime = str(uuid4())
        self.slots = [None] * CAPACITY
        self.index = {}
        self.allocated_count = 0
        self._allocated = ()
        self._binding = (id(lifecycle), id(lifecycle.c), id(lifecycle.installation), installation_hash, self.lifetime)

    def check(self):
        try:
            if self._binding != (id(self.lifecycle), id(self.lifecycle.c), id(self.lifecycle.installation), self.installation_hash, self.lifetime):
                raise ValueError
            if (type(self.allocated_count) is not int or self.allocated_count != len(self._allocated)
                    or len(self.slots) != CAPACITY or len(self.index) != self.allocated_count):
                raise ValueError
            for n, slot in enumerate(self.slots):
                if n >= self.allocated_count:
                    if slot is not None:
                        raise ValueError
                    continue
                if slot is not self._allocated[n] or slot.identity() != slot._identity or slot.ordinal != n:
                    raise ValueError
                if slot.c is not self.lifecycle.c or slot.key[:2] != (self.installation_hash, self.lifetime):
                    raise ValueError
                if self.index.get(slot.key[2]) is not slot or set(slot.cells) != set(GATES):
                    raise ValueError
                if tuple(slot.cells[g] is slot._cells[i] for i, g in enumerate(GATES)) != (True, True, True):
                    raise ValueError
                if slot.snapshot is not slot._snapshot:
                    raise ValueError
                subjects = (slot.records[1].calculation_plan_id, slot.key[2],
                            None if slot.snapshot is None else slot.snapshot.program_execution_snapshot_id)
                for gate, subject in zip(GATES, subjects):
                    cell = slot.cells[gate]
                    if cell.subject != subject or type(cell.generation) is not int or not 0 <= cell.generation <= MAX_GENERATION:
                        raise ValueError
                    if cell.state not in {"UNPREPARED", "PENDING", "EXPIRED_UNDECIDED", "CHOSEN", "RECORDED", "UNCERTAIN"}:
                        raise ValueError
                    if cell.state != "UNPREPARED" and (len(cell.ids) != 2 or len(cell.hashes) != 2 or not cell.view_id or not cell.event_id or not cell.view_hash):
                        raise ValueError
                    if cell.state in {"CHOSEN", "RECORDED", "UNCERTAIN"} and (cell.selected not in {"APPROVED", "REJECTED"} or cell.selected_id != cell.ids[cell.selected == "REJECTED"]):
                        raise ValueError
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            self.lifecycle.poison()
            raise Rejected("LIFECYCLE_BLOCKED") from None

    def reserve(self, material, records, spec):
        self.check()
        intake_id = material.payload["intake_id"]
        if intake_id in self.index:
            raise Rejected("CONFLICT")
        if self.allocated_count == CAPACITY:
            raise Rejected("BUSY")
        try:
            slot = Slot(self.allocated_count, (self.installation_hash, self.lifetime, intake_id),
                        self.lifecycle.c, material, records, spec)
            self.slots[self.allocated_count] = slot
            self.index[intake_id] = slot
            self._allocated += (slot,)
            self.allocated_count += 1
            self.check()
            return slot
        except BaseException:
            self.lifecycle.poison()
            raise

    def subject(self, gate, subject):
        self.check()
        if gate not in GATES or not isinstance(subject, str):
            raise Rejected("SCOPE")
        found = [s for s in self._allocated if s.cells[gate].subject == subject]
        if len(found) != 1:
            raise Rejected("SCOPE")
        return found[0], found[0].cells[gate]

    def pair(self, gate, ids):
        self.check()
        if gate not in GATES:
            raise Rejected("SCOPE")
        found = [(s, s.cells[gate]) for s in self._allocated if s.cells[gate].ids == ids]
        if len(found) != 1:
            raise Rejected("SCOPE")
        return found[0]
