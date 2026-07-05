from __future__ import annotations

from dataclasses import dataclass

from carcols_io import normalize_argb_hex


@dataclass
class SirenToolSequence:
    bits: str
    sequencer: int
    color_name: str
    color: str


def parse_sirentool_export(path: str) -> list:
    """Parse a Siren Tool export .txt file and return the deduplicated 'UNIQUE EXPORTS'
    sequences - these are the distinct flash patterns a user can assign to sirens."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    try:
        start = next(i for i, line in enumerate(lines) if line.strip().upper() == "UNIQUE EXPORTS") + 1
    except StopIteration:
        raise ValueError("No 'UNIQUE EXPORTS' section found - this doesn't look like a SirenTool export file.")

    sequences = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or set(stripped) == {"-"}:
            continue
        parts = stripped.split()
        bits = parts[0]
        if len(bits) != 32 or set(bits) - {"0", "1"}:
            continue
        if len(parts) < 4:
            continue
        decimal_str, color_name, hex_str = parts[1], parts[2], parts[3]
        try:
            sequencer = int(decimal_str)
        except ValueError:
            sequencer = int(bits, 2)
        color = normalize_argb_hex(hex_str) or "0xFFFFFFFF"
        sequences.append(SirenToolSequence(bits=bits, sequencer=sequencer, color_name=color_name, color=color))

    if not sequences:
        raise ValueError("No usable sequences found in the UNIQUE EXPORTS section.")
    return sequences
