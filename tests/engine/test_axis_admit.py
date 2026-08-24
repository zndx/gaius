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


def test_unique_topic_ambiguous_two_above() -> None:
    tau = SdgAperture.load().tau
    code, _, reason = unique_topic(
        [("DATAENG", tau + 0.3), ("ENERGY", tau + 0.2)], tau
    )
    assert reason == "ambiguous"
    assert code == ""
