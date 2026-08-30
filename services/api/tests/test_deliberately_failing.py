"""Deliberately failing test to prove Stage 0.7's branch-protection claim:
a PR with a red check cannot be merged. This file and its branch are never
meant to reach main — see the Stage 0.7 conversation record."""


def test_this_is_meant_to_fail():
    assert False, "intentional failure to prove branch protection blocks the merge"
