"""Printer beds and the bed-fit check (F16).

Beds are a plain string setting, `Name XxYxZ` entries split by `;`, so they edit in one
text field: `Bambu Lab A1 mini 180x180x180; Prusa MK4 250x210x220`.
"""

from __future__ import annotations

import re

DEFAULT_BEDS = ("Bambu Lab A1 mini 180x180x180; Bambu Lab X1/P1/A1 256x256x256; "
                "Prusa MK4 250x210x220; Prusa Core One 250x220x270")
DEFAULT_BED = "Bambu Lab X1/P1/A1"

_ENTRY = re.compile(r"^\s*(?P<name>.+?)\s+(?P<x>\d+(?:\.\d+)?)\s*[x×]\s*(?P<y>\d+(?:\.\d+)?)\s*[x×]\s*"
                    r"(?P<z>\d+(?:\.\d+)?)\s*(?:mm)?\s*$", re.I)


def parse_beds(text: str) -> list[dict]:
    """`Name XxYxZ; ...` → [{name, x, y, z}] (mm). Raises ValueError on a bad entry."""
    out = []
    for part in (text or "").split(";"):
        if not part.strip():
            continue
        m = _ENTRY.match(part)
        if not m:
            raise ValueError(f"bed {part.strip()!r} must look like 'Prusa MK4 250x210x220'")
        x, y, z = (float(m[k]) for k in "xyz")
        if not all(10 <= v <= 2000 for v in (x, y, z)):
            raise ValueError(f"bed {m['name']!r}: each size must be 10 to 2000 mm")
        out.append({"name": m["name"].strip(), "x": x, "y": y, "z": z})
    if not out:
        raise ValueError("list at least one bed")
    return out


def format_beds(beds: list[dict]) -> str:
    def n(v: float) -> str:
        return f"{v:g}"
    return "; ".join(f"{b['name']} {n(b['x'])}x{n(b['y'])}x{n(b['z'])}" for b in beds)


def clean_beds(value) -> str:
    """Settings validator: a string or a list of {name, x, y, z} → the canonical string."""
    if isinstance(value, list):
        beds = [{"name": str(b["name"]), "x": float(b["x"]), "y": float(b["y"]), "z": float(b["z"])}
                for b in value]
        return format_beds(parse_beds(format_beds(beds)))
    return format_beds(parse_beds(str(value)))


def bed_label(b: dict) -> str:
    x, y, z = (f"{b[k]:g}" for k in "xyz")
    return f"{x}³" if x == y == z else f"{x}×{y}×{z}"


def fits(size: list[float], bed: dict) -> bool:
    """Whether a part of this bounding-box size fits the bed in some axis-aligned
    orientation (laid on any face): sorted sizes against sorted bed sizes."""
    part = sorted(max(0.0, float(v)) for v in size)
    room = sorted((bed["x"], bed["y"], bed["z"]))
    return all(p <= r + 1e-6 for p, r in zip(part, room, strict=True))


def bed_fit(parts: list[dict], beds: list[dict], chosen: str | None) -> dict | None:
    """The badge's data. `parts`: [{name, size: [x, y, z] mm}] (printable bodies).
    Returns {bed, label, fits, largest: {name, size}, parts, too_big: [names], fits_beds: [names]}."""
    if not parts or not beds:
        return None
    bed = next((b for b in beds if b["name"].lower() == (chosen or "").lower()), beds[0])
    largest = max(parts, key=lambda p: sorted(p["size"])[::-1])
    too_big = [p["name"] for p in parts if not fits(p["size"], bed)]
    return {
        "bed": bed["name"],
        "label": bed_label(bed),
        "fits": not too_big,
        "largest": {"name": largest["name"], "size": [round(v, 1) for v in largest["size"]]},
        "parts": len(parts),
        "too_big": too_big[:20],
        "fits_beds": [b["name"] for b in beds if all(fits(p["size"], b) for p in parts)],
    }


def part_sizes(info: list[dict]) -> list[dict]:
    """Printable parts from inspect_design bodies: visible ones with a bounding box."""
    out = []
    for b in info:
        if b.get("visible") is False:
            continue
        box = b.get("bbox") or {}
        if box.get("min") and box.get("max"):
            out.append({"name": b["name"],
                        "size": [round(hi - lo, 3) for lo, hi in zip(box["min"], box["max"], strict=True)]})
    return out
