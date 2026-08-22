"""WRK occupancy intent for Scheduler/RequestQueueShare."""

from gaius.engine.queue_share import GPU_KEY, PEER, share_for_class
from gaius.engine.sentinel_claim import EXTRACT, HEAVY, LIGHT, MEDIUM, COMPUTE


def test_extract_share_requests_gpu_floor_1() -> None:
    req = share_for_class("article-curate", EXTRACT)
    assert req.peer == PEER
    assert req.workloads[0].wrk == "article-curate"
    assert req.workloads[0].queue == EXTRACT.queue
    assert req.shares[0].queue == EXTRACT.queue
    assert req.shares[0].guaranteed.quantities[GPU_KEY] == 1
    assert req.shares[0].max.quantities[GPU_KEY] == 2


def test_light_and_medium_floors() -> None:
    light = share_for_class("ask-agent", LIGHT)
    assert light.shares[0].guaranteed.quantities[GPU_KEY] == 1
    med = share_for_class("ask-sae", MEDIUM)
    assert med.shares[0].guaranteed.quantities[GPU_KEY] == 2
    heavy = share_for_class("thinking", HEAVY)
    assert heavy.shares[0].guaranteed.quantities[GPU_KEY] == 4
    opt = share_for_class("optillm", COMPUTE)
    assert opt.shares[0].guaranteed.quantities[GPU_KEY] == 0
    assert opt.workloads[0].wrk == "optillm"
