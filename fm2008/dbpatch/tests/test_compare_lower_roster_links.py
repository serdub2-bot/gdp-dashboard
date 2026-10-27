#!/usr/bin/env python3
"""Проверки сопоставления links `04` с ростером нижней лиги."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compare_lower_roster_links import local_candidates, name_prefix_match  # noqa: E402


class LowerRosterLinkTests(unittest.TestCase):
    def test_name_prefix_matches_reserve_forms(self):
        self.assertTrue(name_prefix_match("Волга", "Волга-2-Энергия"))
        self.assertTrue(name_prefix_match("Амур", "Амур-2"))
        self.assertFalse(name_prefix_match("Автодор", "Алания-2"))

    def test_local_candidates_require_same_city_and_linked_zone(self):
        roster = {"club": "Волга", "city": "Ульяновск"}
        links = {(130489, 8050904, 123)}
        lower = [
            {
                "club": "Волга-2-Энергия",
                "city": "Ульяновск",
                "zone": "Приволжье",
                "status": "участник",
            },
            {
                "club": "Волга-2",
                "city": "Тверь",
                "zone": "Приволжье",
                "status": "участник",
            },
            {
                "club": "Волга",
                "city": "Ульяновск",
                "zone": "Черноземье",
                "status": "участник",
            },
            {
                "club": "Другой клуб",
                "city": "Ульяновск",
                "zone": "Приволжье",
                "status": "снялась",
            },
        ]
        self.assertEqual(
            local_candidates(roster, links, lower),
            ({"Волга-2-Энергия"}, {"Волга-2-Энергия"}),
        )

    def test_city_and_region_match_can_be_only_regional(self):
        roster = {"club": "Автодор", "city": "Владикавказ"}
        links = {(130490, 8050903, 50)}
        lower = [{
            "club": "Алания-2",
            "city": "Владикавказ",
            "zone": "ЮФО",
            "status": "участник",
        }]
        self.assertEqual(
            local_candidates(roster, links, lower),
            ({"Алания-2"}, set()),
        )


if __name__ == "__main__":
    unittest.main()
