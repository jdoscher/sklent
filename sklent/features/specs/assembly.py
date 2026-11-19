"""F30 assembly step images: for an assembly, one still per step showing the parts placed so
far, the step's new parts solid in the ink grey and the earlier ones lighter, plus
`<design>-assembly.md` in GitBuilding BuildUp Markdown linking the images.

Steps come from `.sklent.yaml`:

    assembly:
      steps:
        - name: Base and motor bracket
          components: [Base, Motor bracket]     # component (or root body) names
        - name: Wheels
          components: [Wheel]

or, without it, from the design: the root component's own bodies first, then each top-level
component definition in the order it was placed (all of its placements together; SolidCraft
paints per definition, so two copies of a part can't differ within one still).

Headless SolidCraft has no outline or highlight style, so "new" is told apart by tone only
(two greys; no hue), and hidden placements are hidden with `browser.visibility`.
"""

from __future__ import annotations

from typing import Any

NEW = "#8e98a3"  # the ink grey for the parts this step adds
EARLIER = "#e9edf1"  # the white palette's shaded tone for parts already placed


def structure(sc) -> dict[str, Any]:
    """Root bodies and top-level placements: {root_bodies, defs: {comp id: {name, bodies}},
    placements: [{id, component, name}]} from `component.list`."""
    reply = sc.execute("component.list") or {}
    comps = reply.get("components") or []
    by_id = {c.get("id"): c for c in comps}
    root = by_id.get(0) or next((c for c in comps if c.get("parent") is None), {}) or {}
    placements = []
    for ch in root.get("children") or []:
        if isinstance(ch, dict):
            placements.append({"id": ch.get("id"), "component": ch.get("component"), "name": ch.get("name")})

    def bodies_of(cid, seen=()) -> list[str]:
        c = by_id.get(cid) or {}
        out = list(c.get("bodies") or [])
        for ch in c.get("children") or []:
            sub = ch.get("component") if isinstance(ch, dict) else None
            if sub is not None and sub not in seen:
                out += bodies_of(sub, (*seen, cid))
        return out

    defs = {}
    for p in placements:
        cid = p["component"]
        if cid not in defs:
            defs[cid] = {"name": (by_id.get(cid) or {}).get("name") or p["name"], "bodies": bodies_of(cid)}
    return {"root_bodies": list(root.get("bodies") or []), "defs": defs, "placements": placements}


def default_steps(st: dict) -> list[dict[str, Any]]:
    steps = []
    if st["root_bodies"]:
        steps.append({"name": "Base parts", "root_bodies": list(st["root_bodies"]), "components": []})
    order: list = []
    for p in st["placements"]:
        if p["component"] not in order:
            order.append(p["component"])
    for cid in order:
        if not st["defs"][cid]["bodies"]:
            continue  # nothing to see (an empty or construction-only component)
        steps.append({"name": f"Add {st['defs'][cid]['name']}", "root_bodies": [], "components": [cid]})
    return steps


def steps_from_config(st: dict, cfg_steps: list) -> tuple[list[dict], list[str]]:
    """`.sklent.yaml` steps → step dicts; names match component definitions, placements
    (`Arm:1`) or root bodies, case-insensitively. Unknown names are reported."""
    key = lambda s: str(s).strip().casefold()  # noqa: E731
    defs_by_name = {key(d["name"]): cid for cid, d in st["defs"].items()}
    place_by_name = {key(p["name"]): p["component"] for p in st["placements"]}
    roots = {key(b): b for b in st["root_bodies"]}
    steps, unknown = [], []
    for i, s in enumerate(cfg_steps, 1):
        if isinstance(s, str):
            s = {"name": s, "components": [s]}
        if not isinstance(s, dict):
            continue
        names = s.get("components") or s.get("parts") or []
        if isinstance(names, str):
            names = [names]
        step = {"name": str(s.get("name") or f"Step {i}"), "root_bodies": [], "components": []}
        for n in names:
            k = key(n)
            if k in defs_by_name:
                step["components"].append(defs_by_name[k])
            elif k in place_by_name:
                step["components"].append(place_by_name[k])
            elif k in roots:
                step["root_bodies"].append(roots[k])
            else:
                unknown.append(str(n))
        if step["components"] or step["root_bodies"]:
            steps.append(step)
    return steps, unknown


def run_steps(ctx, st: dict, steps: list[dict], stem: str, camera: dict, size: tuple[int, int]) -> list[dict]:
    """Shoot one still per step; returns [{n, name, file, new: [names], count}]. Leaves the
    design with everything it hid shown again (the caller repaints)."""
    sc = ctx.sc
    w, h = size
    all_paths = [[p["id"]] for p in st["placements"]]
    placements_of = {}
    for p in st["placements"]:
        placements_of.setdefault(p["component"], []).append([p["id"]])
    root_visible = [b for b in st["root_bodies"] if b in set(ctx.bodies) and _visible_body(ctx, b)]
    hidden_roots: list[str] = []
    out = []
    try:
        if all_paths:
            sc.execute("browser.visibility", paths=all_paths, visible=False)
        if root_visible:
            sc.execute("browser.visibility", items=root_visible, visible=False)
            hidden_roots = list(root_visible)
        shown_roots: list[str] = []
        shown_comps: list = []
        for n, step in enumerate(steps, 1):
            new_roots = [b for b in step["root_bodies"] if b in hidden_roots and b not in shown_roots]
            new_comps = [c for c in step["components"] if c not in shown_comps]
            paths = [pp for c in new_comps for pp in placements_of.get(c, [])]
            if paths:
                sc.execute("browser.visibility", paths=paths, visible=True)
            if new_roots:
                sc.execute("browser.visibility", items=new_roots, visible=True)
            new_bodies = new_roots + [b for c in new_comps for b in st["defs"].get(c, {}).get("bodies", [])]
            old_bodies = shown_roots + [b for c in shown_comps for b in st["defs"].get(c, {}).get("bodies", [])]
            cmds = []
            if old_bodies:
                cmds.append({"command": "appearance.assign", "params": {"bodies": old_bodies, "color": EARLIER,
                                                                       "opacity": 1.0}})
            if new_bodies:
                cmds.append({"command": "appearance.assign", "params": {"bodies": new_bodies, "color": NEW,
                                                                       "opacity": 1.0}})
            if cmds:
                sc.tool("batch", commands=cmds, verbose=False)
            shown_roots += new_roots
            shown_comps += new_comps
            name = f"{stem}-assembly-{n:02d}.png"
            sc.screenshot(ctx.out_dir / name, camera, w, h)
            count = sum(len(placements_of.get(c, [])) for c in new_comps) + len(new_roots)
            labels = new_roots + [st["defs"][c]["name"] for c in new_comps if c in st["defs"]]
            out.append({"n": n, "name": step["name"], "file": name, "new": labels, "count": count,
                        "qty": {**{b: 1 for b in new_roots},
                                **{st["defs"][c]["name"]: len(placements_of.get(c, [])) for c in new_comps
                                   if c in st["defs"]}}})
    finally:
        if all_paths:
            sc.execute("browser.visibility", paths=all_paths, visible=True)
        if hidden_roots:
            sc.execute("browser.visibility", items=hidden_roots, visible=True)
    return out


def _visible_body(ctx, name: str) -> bool:
    return next((b.get("visible") is not False for b in ctx.info if b.get("name") == name), True)


def buildup(title: str, images: list[dict], spec: dict | None = None) -> str:
    """GitBuilding BuildUp Markdown: one heading per step, its picture, and the parts it adds
    as BuildUp part links (`[Arm]{Qty: 2}`), so GitBuilding builds the page's BOM."""
    lines = [f"# Assembling {title}", ""]
    if spec and spec.get("repo"):
        lines += [f"Made by Sklent from `{spec['path']}` in {spec['repo']} at "
                  f"`{(spec.get('commit') or '')[:10]}`.", ""]
    lines += ["{{BOM}}", ""]
    for st in images:
        lines += [f"## Step {st['n']}: {st['name']}", "", f"![Step {st['n']}: {st['name']}]({st['file']})", ""]
        for name, qty in st["qty"].items():
            lines.append(f"* Add [{_md(name)}]{{Qty: {qty}}}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _md(s: str) -> str:
    return str(s).replace("[", "(").replace("]", ")")


def fit_camera(box, size: tuple[int, int], pitch: float) -> dict:
    """One perspective camera (the stills' front-right angle) that frames the whole assembly,
    so every step's picture lines up with the next."""
    from sklent.render import STILL_YAW, camera, fit_distance

    target, dist = fit_distance(*box, size[0], size[1], pitch, [STILL_YAW], margin=1.06)
    return camera(target, STILL_YAW, pitch, dist)
