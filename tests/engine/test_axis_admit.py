import pytest

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


def test_remainder_spans_none_and_ambiguous_not_overlap() -> None:
    from gaius.engine.services.axis_admit import remainder_spans
    from gaius.flows.prospects.windows import TokenWindow

    windows = [
        TokenWindow(0, 10, "a", admitted=True, reason="admitted", margin=0.9),
        TokenWindow(10, 20, "b", admitted=False, reason="none", margin=0.01),
        TokenWindow(20, 30, "c", admitted=False, reason="ambiguous", margin=0.4),
        TokenWindow(30, 40, "d", admitted=False, reason="overlap", margin=0.8),
    ]
    spans = remainder_spans("abcdefghij" * 5, entry_id="e1", axis="ambient", windows=windows)
    assert {s["reason"] for s in spans} == {"none", "ambiguous"}
    assert all(s["axis"] == "ambient" for s in spans)


@pytest.mark.asyncio
async def test_record_remainder_fail_open_without_pool() -> None:
    from gaius.engine.services.theta_scratch import record_remainder_fail_open

    n = await record_remainder_fail_open(None, [{"reason": "none", "start": 0, "end": 1}])
    assert n == 0


@pytest.mark.asyncio
async def test_record_remainder_inserts_vertex_rows() -> None:
    from gaius.engine.services.theta_scratch import record_remainder

    class _Conn:
        def __init__(self) -> None:
            self.sql: list[str] = []
            self.rows: list = []

        async def fetchval(self, sql: str, *args: object) -> str:
            self.sql.append(sql)
            return "ok"

        async def executemany(self, sql: str, rows: list) -> None:
            self.sql.append(sql)
            self.rows.extend(rows)

    conn = _Conn()
    n = await record_remainder(
        conn,
        [
            {
                "axis": "ambient",
                "entry_id": "ab",
                "start": 0,
                "end": 12,
                "reason": "none",
                "margin": 0.02,
            }
        ],
        aperture="sdg_aperture",
        c_epoch="pin",
        tau=0.1,
    )
    assert n == 1
    assert "theta_scratch_vertex_tier0" in conn.sql[-1]
    assert conn.rows[0][3] == "window"
    assert conn.rows[0][9] == "none"


def test_unique_topic_ambiguous_two_above() -> None:
    tau = SdgAperture.load().tau
    code, _, reason = unique_topic(
        [("DATAENG", tau + 0.3), ("ENERGY", tau + 0.2)], tau
    )
    assert reason == "ambiguous"
    assert code == ""
