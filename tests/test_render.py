import math

import numpy as np
from PIL import Image

from sklent import palette
from sklent.render import FOV, RenderOptions, _basis, discord_kbps, fit_distance


def _project(p, target, yaw, pitch, dist, w, h):
    f, r, u = _basis(yaw, pitch)
    q = np.array(p) - np.array(target)
    depth = q @ f + dist
    tan_v = math.tan(FOV / 2)
    return (q @ r) / depth / (tan_v * w / h), (q @ u) / depth / tan_v  # -1..1 = in frame


def test_fit_keeps_every_corner_in_frame_at_every_yaw():
    lo, hi = [-110, -63, 0], [110, 63, 142]  # long and tall, off-origin in z
    pitch = math.radians(24)
    yaws = [2 * math.pi * i / 36 for i in range(36)]
    for w, h in ((1920, 1080), (1080, 1920)):
        target, dist = fit_distance(lo, hi, w, h, pitch, yaws, margin=1.08)
        worst = 0.0
        for yaw in yaws:
            for x in (lo[0], hi[0]):
                for y in (lo[1], hi[1]):
                    for z in (lo[2], hi[2]):
                        sx, sy = _project([x, y, z], target, yaw, pitch, dist, w, h)
                        worst = max(worst, abs(sx), abs(sy))
        assert worst <= 1 / 1.08 + 1e-9
        assert worst > 0.8  # and it isn't lazily tiny


def test_basis_matches_solidcraft_front_view():
    f, r, u = _basis(0, 0)  # eye at -Y looking +Y, +X right, Z up
    assert np.allclose(f, [0, 1, 0]) and np.allclose(r, [1, 0, 0]) and np.allclose(u, [0, 0, 1])


def test_options_validate():
    RenderOptions().validate()
    for bad in ({"palette": "red"}, {"seconds": 99}, {"styles": ["toon"]}, {"fps": 7}):
        try:
            RenderOptions(**bad).validate()
        except ValueError:
            continue
        raise AssertionError(f"{bad} should be rejected")


def test_discord_budget_stays_under_10mb():
    for s in (2, 8, 30):
        assert discord_kbps(s) * s / 8 / 1000 < 9.5


def test_palettes_are_neutral():
    for p in palette.PALETTES.values():
        for hex_ in (p.shaded, p.wireframe):
            rgb = np.array([[[int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]]], dtype=np.float32)
            assert not palette._saturated(rgb).any(), hex_


def test_clamp_greys_out_colour_and_leaves_grey_alone(tmp_path):
    img = np.zeros((40, 40, 3), np.uint8)
    img[:, :] = (226, 232, 240)  # the cool background
    img[10:20, 10:20] = (200, 30, 30)  # a red face
    img[25:35, 25:35] = (167, 176, 186)  # cool-grey part
    img[36:38, :] = (40, 44, 52)  # SolidCraft's dark slate edge line
    path = tmp_path / "f.png"
    Image.fromarray(img).save(path)
    assert palette.colour_fraction(path) > 0.05
    changed = palette.clamp(path)
    assert abs(changed - 100 / 1600) < 1e-6
    out = np.asarray(Image.open(path))
    assert palette.colour_fraction(path) == 0
    for y, x in ((0, 0), (30, 30), (37, 5)):
        assert (out[y, x] == img[y, x]).all()
    assert palette.clamp(path) == 0


def test_guard_flags_pale_and_dark_colours():
    rgb = np.array([[[240, 200, 200], [240, 230, 180], [80, 20, 20], [60, 45, 40]]], np.float32) / 255
    assert palette._saturated(rgb).tolist() == [[True, True, True, False]]


def test_clamp_all_only_rewrites_when_colour_is_found(tmp_path):
    from sklent.render import clamp_all
    grey = np.full((8, 8, 3), 170, np.uint8)
    frames = []
    for i in range(8):
        f = tmp_path / f"f{i}.png"
        Image.fromarray(grey).save(f)
        frames.append(f)
    assert clamp_all(frames, []) == 0
    red = grey.copy()
    red[:4] = (200, 30, 30)
    Image.fromarray(red).save(frames[4])  # a sampled frame
    Image.fromarray(red).save(frames[5])  # an unsampled one: still cleaned
    assert clamp_all(frames, []) == 0.5
    assert palette.colour_fraction(frames[5]) == 0


def test_bounds_ignore_hidden_bodies():
    from sklent.solidcraft import SolidCraft
    bodies = [
        {"name": "rover", "visible": True, "bbox": {"min": [-100, -50, 0], "max": [100, 50, 120]}},
        {"name": "track", "visible": False, "bbox": {"min": [-800, -170, -4], "max": [800, 170, 0]}},
        {"name": "old file", "bbox": {"min": [0, 0, 0], "max": [150, 10, 10]}},  # no flag: visible
    ]
    assert SolidCraft.bounds(bodies) == ([-100, -50, 0], [150, 50, 120])
    assert SolidCraft.bounds([bodies[1]]) is None
