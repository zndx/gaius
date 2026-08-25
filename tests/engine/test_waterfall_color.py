from gaius.engine.services.waterfall_color import (
    FLASH_NEG,
    FLASH_POS,
    dkcyan2,
    flash_rgb,
    gpu_rgb,
    motion_mix,
    onset_field,
    overlay_motion,
    pack_gpu,
    signed_rgb,
    unpack_gpu,
)


def test_pack_roundtrip() -> None:
    for p, u in ((0.3, 1.0), (-0.02, 0.0), (0.8, 0.7), (0.0, 0.5)):
        p2, u2, on = unpack_gpu(pack_gpu(p, u))
        assert on
        assert abs(p2 - p) < 0.02
        assert abs(u2 - u) < 0.002


def test_absent_is_zero() -> None:
    p, u, on = unpack_gpu(0.0)
    assert on is False
    assert p == 0.0 and u == 0.0


def test_dkcyan2_corners() -> None:
    assert dkcyan2(0.0, 0.0) == (0xD3, 0xD3, 0xD3)
    assert dkcyan2(1.0, 0.0) == (0x62, 0x77, 0xA5)
    assert dkcyan2(0.0, 1.0) == (0x69, 0x9E, 0x74)
    assert dkcyan2(1.0, 1.0) == (0x31, 0x59, 0x5B)


def test_gpu_steady_is_dkcyan2_not_amber() -> None:
    idle = gpu_rgb(0.0, 0.0)
    hot = gpu_rgb(0.8, 1.0)
    assert idle == (0xD3, 0xD3, 0xD3)
    assert hot[2] >= hot[0]  # teal, not amber/red


def test_sharp_positive_mixes_red() -> None:
    base = gpu_rgb(0.2, 0.2)
    flashed = gpu_rgb(0.4, 0.2, prev_power=0.2, prev_util=0.2)
    assert flashed[0] > base[0]
    assert flashed != FLASH_POS


def test_sharp_negative_mixes_blue() -> None:
    flashed = overlay_motion((0x73, 0x90, 0x91), -0.18)
    assert flashed[2] > flashed[0]
    assert flashed != FLASH_NEG


def test_signed_zero_is_dkcyan2_origin() -> None:
    assert signed_rgb(0.0) == (0xD3, 0xD3, 0xD3)


def test_onset_impulse_peak_and_shoulders() -> None:
    e = onset_field([0.0, 0.0, 1.0, 0.0, 0.0])
    peak_i = max(range(len(e)), key=lambda i: abs(e[i]))
    assert peak_i in (2, 3)  # upstroke or downstroke
    assert abs(e[2]) > abs(e[1]) > 0.05
    assert abs(e[3]) > abs(e[4]) > 0.0 or abs(e[3]) > 0.5


def test_onset_slow_ramp_spreads() -> None:
    e = onset_field([0.0, 0.2, 0.4, 0.6, 0.8])
    assert all(x >= 0 for x in e[1:])
    assert e[2] > 0.15


def test_motion_mix_is_principal() -> None:
    assert motion_mix(0.02) == 0.0
    assert motion_mix(0.63) > motion_mix(0.2) > 0.15
    assert motion_mix(1.5) > 0.85


def test_flash_rgb_is_graded() -> None:
    lo = flash_rgb(0.25)
    hi = flash_rgb(1.4)
    assert lo != hi
    # deeper stop is darker overall
    def luma(rgb: tuple[int, int, int]) -> float:
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    assert luma(hi) < luma(lo)
    blo = flash_rgb(-0.25)
    bhi = flash_rgb(-1.4)
    assert luma(bhi) < luma(blo)
