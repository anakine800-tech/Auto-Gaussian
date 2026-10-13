"""Private full-precision geometry, descriptor, and clustering primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math


def _center(points: Sequence[Sequence[float]]) -> list[list[float]]:
    centroid = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
    return [[point[axis] - centroid[axis] for axis in range(3)] for point in points]


def _largest_eigenvector_symmetric(matrix: list[list[float]]) -> list[float]:
    size = len(matrix)
    values = [row[:] for row in matrix]
    vectors = [[1.0 if row == column else 0.0 for column in range(size)] for row in range(size)]
    for _ in range(100):
        left, right = max(
            ((i, j) for i in range(size) for j in range(i + 1, size)),
            key=lambda pair: abs(values[pair[0]][pair[1]]),
        )
        if values[left][right] == 0.0:
            break
        angle = 0.5 * math.atan2(
            2.0 * values[left][right],
            values[right][right] - values[left][left],
        )
        cosine, sine = math.cos(angle), math.sin(angle)
        for index in range(size):
            a, b = values[index][left], values[index][right]
            values[index][left], values[index][right] = (
                cosine * a - sine * b,
                sine * a + cosine * b,
            )
        for index in range(size):
            a, b = values[left][index], values[right][index]
            values[left][index], values[right][index] = (
                cosine * a - sine * b,
                sine * a + cosine * b,
            )
        for index in range(size):
            a, b = vectors[index][left], vectors[index][right]
            vectors[index][left], vectors[index][right] = (
                cosine * a - sine * b,
                sine * a + cosine * b,
            )
    column = max(range(size), key=lambda index: values[index][index])
    vector = [vectors[row][column] for row in range(size)]
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        raise ValueError("RMSD rotation is numerically indeterminate")
    return [value / norm for value in vector]


def mapped_rmsd(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    indices: Sequence[int],
) -> float:
    if len(left) != len(right) or not indices:
        raise ValueError("mapped RMSD requires equal atom counts and a non-empty selection")
    first = _center([left[index] for index in indices])
    second = _center([right[index] for index in indices])
    sxx = sum(a[0] * b[0] for a, b in zip(first, second))
    sxy = sum(a[0] * b[1] for a, b in zip(first, second))
    sxz = sum(a[0] * b[2] for a, b in zip(first, second))
    syx = sum(a[1] * b[0] for a, b in zip(first, second))
    syy = sum(a[1] * b[1] for a, b in zip(first, second))
    syz = sum(a[1] * b[2] for a, b in zip(first, second))
    szx = sum(a[2] * b[0] for a, b in zip(first, second))
    szy = sum(a[2] * b[1] for a, b in zip(first, second))
    szz = sum(a[2] * b[2] for a, b in zip(first, second))
    scalar, x, y, z = _largest_eigenvector_symmetric(
        [
            [sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
            [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
            [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
            [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz],
        ]
    )
    rotation = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * scalar), 2 * (x * z + y * scalar)],
        [2 * (x * y + z * scalar), 1 - 2 * (x * x + z * z), 2 * (y * z - x * scalar)],
        [2 * (x * z - y * scalar), 2 * (y * z + x * scalar), 1 - 2 * (x * x + y * y)],
    ]
    rotated = [
        [sum(rotation[row][column] * point[column] for column in range(3)) for row in range(3)]
        for point in first
    ]
    return math.sqrt(
        sum(
            sum((a[axis] - b[axis]) ** 2 for axis in range(3))
            for a, b in zip(rotated, second)
        )
        / len(indices)
    )


def minimum_pair_distance(coordinates: Sequence[Sequence[float]]) -> float:
    if len(coordinates) < 2:
        return math.inf
    return min(
        math.dist(coordinates[left], coordinates[right])
        for left in range(len(coordinates))
        for right in range(left + 1, len(coordinates))
    )


def descriptor_distance(kind: str, left: object, right: object) -> float:
    if kind == "scalar":
        return abs(float(left) - float(right))
    if kind == "periodic_degrees":
        return abs((float(left) - float(right) + 180.0) % 360.0 - 180.0)
    if kind == "categorical_set":
        first, second = set(left), set(right)
        similarity = len(first & second) / len(first | second) if first or second else 1.0
        return 1.0 - similarity
    raise ValueError(f"unsupported descriptor distance kind {kind!r}")


def pair_distance(
    left: Mapping[str, object],
    right: Mapping[str, object],
    *,
    atom_indices: Sequence[int],
    mapped_rmsd_weight: float,
    descriptor_policy: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    left_coordinates = left["coordinates_angstrom"]
    right_coordinates = right["coordinates_angstrom"]
    assert isinstance(left_coordinates, Sequence) and isinstance(right_coordinates, Sequence)
    rmsd = mapped_rmsd(left_coordinates, right_coordinates, atom_indices)
    components: dict[str, float] = {"mapped_rmsd": rmsd}
    composite = mapped_rmsd_weight * rmsd
    left_descriptors = left["descriptors"]
    right_descriptors = right["descriptors"]
    assert isinstance(left_descriptors, Mapping) and isinstance(right_descriptors, Mapping)
    for policy in descriptor_policy:
        name = policy["name"]
        left_value = left_descriptors[name]["value"]
        right_value = right_descriptors[name]["value"]
        distance = descriptor_distance(str(policy["kind"]), left_value, right_value)
        components[f"descriptor:{name}"] = distance
        composite += float(policy["weight"]) * distance
    return {
        "components": components,
        "composite_distance": composite,
    }


def union_clusters(member_ids: Sequence[str], comparisons: Sequence[Mapping[str, object]]) -> list[list[str]]:
    indices = {member_id: index for index, member_id in enumerate(member_ids)}
    parents = list(range(len(member_ids)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for comparison in comparisons:
        if comparison["decision"] != "duplicate":
            continue
        left, right = (indices[item] for item in comparison["member_ids"])
        first, second = find(left), find(right)
        if first != second:
            parents[max(first, second)] = min(first, second)
    groups: dict[int, list[str]] = {}
    for member_id in member_ids:
        groups.setdefault(find(indices[member_id]), []).append(member_id)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])
