from datetime import datetime, timedelta, timezone

from cases import DUPLICATE_RADIUS_M, case_for, distance_m, group_into_cases, votes_of
from privacy.report_status import ReportRecord

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
STUTTGART = (48.7758, 9.1829)


def entry(report_id, lat=STUTTGART[0], lon=STUTTGART[1], category="pothole", days_ago=0.0):
    record = ReportRecord(
        report_id, "user", "drafted",
        sanitized={"location": {"lat": lat, "lon": lon}} if lat is not None else {"location": {}},
        classification={"category": category},
    )
    return record, NOW - timedelta(days=days_ago)


def north(meters):
    """A latitude that is this many meters north of the start."""
    return STUTTGART[0] + meters / 111_195


def test_distance_in_meters():
    assert abs(distance_m(*STUTTGART, north(100), STUTTGART[1]) - 100) < 1
    assert distance_m(*STUTTGART, *STUTTGART) == 0


def test_the_same_category_at_the_same_place_is_one_case():
    cases = group_into_cases([entry("a"), entry("b", lat=north(10))])
    assert len(cases) == 1 and votes_of(cases[0]) == 2


def test_the_limit_is_forty_meters():
    assert DUPLICATE_RADIUS_M == 40
    assert len(group_into_cases([entry("a"), entry("b", lat=north(39))])) == 1
    assert len(group_into_cases([entry("a"), entry("b", lat=north(41))])) == 2


def test_another_category_is_another_case():
    assert len(group_into_cases([entry("a"), entry("b", category="graffiti")])) == 2


def test_a_case_stays_open_for_thirty_days_from_its_first_report():
    cases = group_into_cases([entry("old", days_ago=31), entry("new", days_ago=0)])
    assert len(cases) == 2  # the old one is closed by now, the new report starts a case
    assert len(group_into_cases([entry("old", days_ago=29), entry("new", days_ago=0)])) == 1


def test_the_oldest_report_is_the_anchor_and_the_newest_case_comes_first():
    cases = group_into_cases([entry("new", days_ago=1), entry("old", days_ago=3), entry("other", lat=north(500), days_ago=0.5)])
    assert [[record.report_id for record, _ in case] for case in cases] == [["other"], ["old", "new"]]


def test_a_report_without_a_position_or_category_is_a_case_of_its_own():
    no_position = entry("a", lat=None)
    no_category = (ReportRecord("b", "user", "drafted", sanitized={"location": {"lat": 1.0, "lon": 1.0}}, classification=None), NOW)
    cases = group_into_cases([no_position, no_position[0:1] + (NOW,), no_category, entry("c"), entry("d")])
    assert sorted(len(case) for case in cases) == [1, 1, 1, 2]


def test_the_nearest_case_wins_when_two_are_in_reach():
    left, right = entry("left", lat=north(0), days_ago=5), entry("right", lat=north(70), days_ago=4)
    middle = entry("middle", lat=north(50), days_ago=0)  # 50 m from the left, 20 m from the right
    cases = group_into_cases([left, right, middle])
    joined = next(case for case in cases if len(case) == 2)
    assert {record.report_id for record, _ in joined} == {"right", "middle"}


def test_case_for_finds_the_case_of_one_report():
    first, second, far = entry("a", days_ago=2), entry("b"), entry("c", lat=north(900))
    case = case_for([first, second, far], second[0])
    assert [record.report_id for record, _ in case] == ["a", "b"]
    assert case_for([first], ReportRecord("zzz", "user", "drafted")) == []
