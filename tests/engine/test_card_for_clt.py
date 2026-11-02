"""CLT takes a whole card, and moves when the preferred card is shared."""

from gaius.engine.resources.gpu_occupancy import GpuOccupant, card_for_clt


def _occ(gpu: int, workload: str, memory: int = 8000) -> GpuOccupant:
    return GpuOccupant(
        gpu=gpu, pid=1000 + gpu, memory_mib=memory, command=workload, workload=workload
    )


def test_preferred_card_when_it_is_free():
    assert card_for_clt(4, occupants=[_occ(0, "resident-9")]) == 4


def test_moves_off_a_card_thinking_holds():
    held = [_occ(gpu, "thinking") for gpu in (1, 2, 3, 4)]
    assert card_for_clt(4, occupants=held) == 5


def test_ignores_its_own_worker_on_the_preferred_card():
    assert card_for_clt(4, occupants=[_occ(4, "clt", 6600)]) == 4


def test_fails_when_every_card_is_shared():
    held = [_occ(gpu, "thinking") for gpu in range(6)]
    try:
        card_for_clt(4, occupants=held)
    except RuntimeError as exc:
        assert "#CLT.00000001.NOGPU" in str(exc)
    else:
        raise AssertionError("expected NOGPU")
