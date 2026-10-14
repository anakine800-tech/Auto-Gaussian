"""Validate the xcontrol subset for CREST constraints and xTB scans."""
import math
import re


def validate(text, n_atoms, *, allow_scan=False):
    # xcontrol also accepts file-writing and external-program directives. Match
    # whole lines so none can ride along with an otherwise valid constraint.
    if re.search(r'[^\x20-\x7e\t\r\n]', text):
        raise ValueError('Constraints must contain only ASCII text and whitespace')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    scan_lines = []
    if allow_scan and '$scan' in lines:
        index = lines.index('$scan')
        scan_lines = lines[index + 1:-1]
        if lines[-1] != '$end' or len(scan_lines) != 1:
            raise ValueError('$scan requires exactly one scan line and $end')
        lines = lines[:index]
        # xcontrol accepts either a new block or an explicit $end separator.
        if not lines or lines[-1] != '$end':
            lines.append('$end')
    definitions = []
    if len(lines) < 2 or lines[0] != '$constrain' or lines[-1] != '$end':
        raise ValueError('Constraints require one $constrain block closed by $end')

    def atom(value):
        if not re.fullmatch(r'[0-9]+', value) or not 1 <= int(value) <= n_atoms:
            raise ValueError(f'Constraint atom index must be between 1 and {n_atoms}')
        return int(value)

    def number(value):
        if not re.fullmatch(r'[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?', value):
            raise ValueError('Constraint value must be a finite number')
        if not math.isfinite(float(value)):
            raise ValueError('Constraint value must be a finite number')

    for line in lines[1:-1]:
        force = re.fullmatch(r'force constant\s*=\s*(.+)', line)
        if force:
            number(force[1])
            continue
        entry = re.fullmatch(r'(atoms|distance|angle|dihedral)\s*:\s*(.+)', line)
        if not entry:
            raise ValueError('Unsupported constraint directive; only $constrain entries are allowed')
        kind, value = entry.groups()
        fields = [field.strip() for field in value.split(',')]
        if kind == 'atoms':
            for field in fields:
                ends = field.split('-')
                if len(ends) == 1:
                    atom(ends[0])
                elif len(ends) == 2:
                    start, end = (atom(end.strip()) for end in ends)
                    if start > end:
                        raise ValueError('Constraint atom range must be ascending')
                else:
                    raise ValueError('Invalid constraint atom list')
        else:
            count = {'distance': 2, 'angle': 3, 'dihedral': 4}[kind]
            if len(fields) != count + 1:
                raise ValueError(f'{kind} requires {count} atom indices and a value or auto')
            for field in fields[:-1]:
                atom(field)
            if fields[-1] != 'auto':
                number(fields[-1])
            definitions.append(dict(kind={'distance': 'B', 'angle': 'A', 'dihedral': 'D'}[kind],
                                    atoms=list(map(int, fields[:-1]))))

    if not scan_lines:
        return None
    match = re.fullmatch(r'([0-9]+)\s*:\s*([^,]+),\s*([^,]+),\s*([0-9]+)', scan_lines[0])
    if not match or not 1 <= int(match[1]) <= len(definitions):
        raise ValueError('$scan must reference a defined internal coordinate constraint')
    number(match[2].strip())
    number(match[3].strip())
    steps = int(match[4])
    if not 1 <= steps <= 100:
        raise ValueError('xTB scan steps must be 1–100')
    start, end = float(match[2]), float(match[3])
    step_size = (end - start) / (steps - 1) if steps > 1 else 0.0
    if not math.isfinite(step_size):
        raise ValueError('xTB scan step size must be finite')
    return dict(coordinate=definitions[int(match[1]) - 1], constraint_index=int(match[1]),
                start=start, end=end, steps=steps, expected_points=steps,
                step_size=step_size)
