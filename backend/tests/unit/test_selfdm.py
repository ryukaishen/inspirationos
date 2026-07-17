"""Owner detection and self-DM candidate flagging heuristics."""

from app.services.ingest.instagram.selfdm import detect_owner, is_self_dm_candidate

OWNER = "Synthetic Owner"
FRIEND = "Synthetic Friend"


class TestDetectOwner:
    def test_personal_information_name_wins(self) -> None:
        assert detect_owner(OWNER, [[FRIEND, "Other"], ["Third"]]) == OWNER

    def test_fallback_common_participant_across_threads(self) -> None:
        threads = [[OWNER, FRIEND], [OWNER], [OWNER, "Synthetic Other"]]
        assert detect_owner(None, threads) == OWNER

    def test_fallback_single_two_person_thread_is_ambiguous(self) -> None:
        assert detect_owner(None, [[OWNER, FRIEND]]) is None

    def test_fallback_no_common_participant(self) -> None:
        assert detect_owner(None, [[OWNER], [FRIEND]]) is None

    def test_no_threads(self) -> None:
        assert detect_owner(None, []) is None

    def test_single_sole_participant_thread(self) -> None:
        assert detect_owner(None, [[OWNER]]) == OWNER


class TestIsSelfDmCandidate:
    def test_sole_participant_is_candidate(self) -> None:
        assert is_self_dm_candidate("Any title", [OWNER], OWNER) is True

    def test_title_matching_owner_is_candidate(self) -> None:
        assert is_self_dm_candidate(OWNER, [OWNER, FRIEND], OWNER) is True

    def test_regular_thread_is_not_candidate(self) -> None:
        assert is_self_dm_candidate(FRIEND, [OWNER, FRIEND], OWNER) is False

    def test_without_owner_nothing_is_candidate(self) -> None:
        assert is_self_dm_candidate(OWNER, [OWNER], None) is False
