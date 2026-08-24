from gaius.engine.services.axis_admit import unique_topic
from gaius.engine.services.sdg_aperture import SdgAperture


def test_unique_topic_none_below_tau() -> None:
    tau = SdgAperture.load().tau
    code, score, reason = unique_topic([("DATAENG", tau / 2)], tau)
    assert reason == "none"
    assert code == ""


def test_unique_topic_admitted_one_above() -> None:
    tau = SdgAperture.load().tau
    code, _, reason = unique_topic([("DATAENG", tau + 0.2), ("MFG", tau / 2)], tau)
    assert reason == "admitted"
    assert code == "DATAENG"


def test_parse_search_buffer_requests() -> None:
    from gaius.engine.services.cognition_synthesis import parse_search_requests

    text = "SEARCH_BUFFER ambient seL4 proofs\nSEARCH_BUFFER publish ColBERT\n"
    reqs = parse_search_requests(text)
    assert reqs[0] == ("ambient", "seL4 proofs")
    assert reqs[1] == ("publish", "ColBERT")


def test_buffer_search_finds_full_text() -> None:
    import asyncio

    from gaius.engine.services.ambient_buffer import AmbientBuffer, BufferEntry, BufferRole

    async def _run() -> None:
        buf = AmbientBuffer(max_bytes=50_000)
        await buf.add_entry(
            BufferEntry.create(BufferRole.CONTENT, "seL4 AArch64 proofs on HN")
        )
        hits = await buf.search("seL4 proofs")
        assert hits and "seL4" in hits[0].content

    asyncio.run(_run())


def test_unique_topic_ambiguous_two_above() -> None:
    tau = SdgAperture.load().tau
    code, _, reason = unique_topic(
        [("DATAENG", tau + 0.3), ("ENERGY", tau + 0.2)], tau
    )
    assert reason == "ambiguous"
    assert code == ""
