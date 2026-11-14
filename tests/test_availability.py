from railengine.availability import parse_status
from railengine.models import StatusState


def test_available_variants():
    assert parse_status("AVAILABLE-0023").state is StatusState.AVAILABLE
    assert parse_status("AVAILABLE-0023").number == 23
    assert parse_status("AVL 5").state is StatusState.AVAILABLE


def test_current_availability():
    s = parse_status("CURR_AVBL-0005")
    assert s.state is StatusState.CURR_AVBL and s.number == 5
    assert s.confirmable


def test_rac():
    s = parse_status("RAC 12")
    assert s.state is StatusState.RAC and s.number == 12
    assert s.confirmable


def test_waitlist_family():
    assert parse_status("GNWL 134/WL 120").state is StatusState.WAITLIST
    assert parse_status("GNWL 134/WL 120").number == 134
    assert parse_status("RLWL 45/WL 40").state is StatusState.WAITLIST
    assert not parse_status("GNWL 134/WL 120").confirmable


def test_regret_before_wl():
    # "REGRET/WL" must be REGRET, not waitlist.
    assert parse_status("REGRET/WL").state is StatusState.REGRET


def test_departed_and_unknown():
    assert parse_status("TRAIN DEPARTED").state is StatusState.DEPARTED
    assert parse_status("").state is StatusState.NOT_AVAILABLE
    assert parse_status("garbage").state is StatusState.NOT_AVAILABLE


def test_status_ranking_order():
    order = [
        StatusState.AVAILABLE, StatusState.CURR_AVBL, StatusState.RAC,
        StatusState.WAITLIST, StatusState.REGRET, StatusState.NOT_AVAILABLE,
        StatusState.DEPARTED,
    ]
    assert [s.rank for s in order] == sorted(s.rank for s in order)
