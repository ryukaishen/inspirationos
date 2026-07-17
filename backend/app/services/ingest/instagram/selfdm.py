"""Owner-name detection and self-DM candidate flagging.

The owner is taken from ``personal_information.json`` when present; otherwise
the participant common to **all** threads (only if exactly one such name
exists — anything ambiguous yields no owner, and therefore no candidates).
A thread is only ever a *candidate*: the user confirms in the UI, never the
code (see PRODUCT_SPEC.md).

Operates on plain titles/name lists so it works over full parsed threads and
over scan summaries alike.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def detect_owner(
    personal_name: str | None, participant_lists: Iterable[Sequence[str]]
) -> str | None:
    if personal_name:
        return personal_name
    common: set[str] | None = None
    for names in participant_lists:
        common = set(names) if common is None else common & set(names)
    if common is not None and len(common) == 1:
        return next(iter(common))
    return None


def is_self_dm_candidate(
    title: str | None, participant_names: Sequence[str], owner: str | None
) -> bool:
    if owner is None:
        return False
    return set(participant_names) == {owner} or title == owner
