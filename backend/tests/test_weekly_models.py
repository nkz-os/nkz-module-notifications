import pytest

from app.digest.weekly.models import Contribution


def _raw(**over):
    raw = {
        "version": 1,
        "complete": True,
        "tasks": [
            {
                "id": "t1",
                "subject": {"type": "parcel", "id": "urn:x:1", "name": "Plot A"},
                "kind": "irrigate",
                "when": {"type": "date", "date": "2026-11-09"},
                "text": {"es": {"title": "Regar", "why": "seco"}, "en": {"title": "Irrigate"}},
                "link": {"kind": "open_parcel", "params": {"id": "1"}},
                "relatedAlertId": None,
            }
        ],
        "changes": [
            {"subject": {"type": "parcel", "id": "u", "name": "A"}, "text": {"en": {"title": "x"}}, "link": None}
        ],
        "figures": [
            {
                "subject": {"type": "parcel", "id": "u", "name": "A"},
                "metrics": [{"key": "rain_mm", "value": 1.5, "origin": "estimated"}],
            }
        ],
    }
    raw.update(over)
    return raw


def test_parse_ok():
    c = Contribution.parse(_raw())
    assert c.complete is True
    assert c.tasks[0].when.date == "2026-11-09"
    assert c.figures[0].metrics[0].origin == "estimated"


def test_contribution_rejects_other_version():
    with pytest.raises(ValueError):
        Contribution.parse(_raw(version=2))


def test_complete_required():
    raw = _raw()
    del raw["complete"]
    with pytest.raises(ValueError):
        Contribution.parse(raw)


def test_unknown_subject_type_and_kind_accepted():
    raw = _raw()
    raw["tasks"][0]["subject"] = {"type": "farm", "id": "", "name": "Farm"}
    raw["tasks"][0]["kind"] = "brand_new_kind"
    raw["tasks"][0]["link"] = None
    raw["tasks"][0]["when"] = {"type": "undated", "date": None}
    raw["tasks"][0]["extra_field"] = 1
    c = Contribution.parse(raw)
    assert c.tasks[0].subject.id == ""
    assert c.tasks[0].link is None
    assert c.tasks[0].when.date is None


def test_bad_origin_rejected():
    raw = _raw()
    raw["figures"][0]["metrics"][0]["origin"] = "magic"
    with pytest.raises(ValueError):
        Contribution.parse(raw)
