#!/usr/bin/env python3
"""Regression coverage for the canonical IR interaction contract."""

from __future__ import annotations

import unittest

from ir_contracts import (
    INTERACTION_CONTRACT_VERSION,
    browser_interaction_contract,
    interaction_contract,
)


class InteractionContractTests(unittest.TestCase):
    def test_static_metadata_never_implies_interactivity(self) -> None:
        for node in (
            {"type": "container", "action": {}},
            {"type": "text", "source": {"symbol": "data-action"}},
            {"type": "card", "semantics": {"role": "article", "label": "Status"}},
        ):
            self.assertFalse(interaction_contract(node)["interactive"])

    def test_native_action_and_semantic_controls_share_one_contract(self) -> None:
        cases = (
            ({"type": "button"}, "native-node"),
            ({"type": "container", "action": {"type": "navigate", "target": "next"}}, "action"),
            ({"type": "container", "semantics": {"role": "button", "label": "Open"}}, "semantic-role"),
        )
        for node, expected_source in cases:
            contract = interaction_contract(node)
            self.assertTrue(contract["interactive"])
            self.assertTrue(contract["keyboardExpected"])
            self.assertIn(expected_source, contract["sources"])

    def test_unsupported_or_empty_action_is_not_an_interaction_signal(self) -> None:
        self.assertFalse(interaction_contract({"type": "container", "action": {"type": ""}})["interactive"])
        self.assertFalse(interaction_contract({"type": "container", "action": {"type": "submit"}})["interactive"])

    def test_browser_contract_is_generated_from_the_same_constants(self) -> None:
        payload = browser_interaction_contract()
        self.assertEqual(payload["version"], INTERACTION_CONTRACT_VERSION)
        self.assertIn("button", payload["nativeNodeTypes"])
        self.assertIn("button", payload["semanticRoles"])
        self.assertIn("navigate", payload["actionTypes"])


if __name__ == "__main__":
    unittest.main()
