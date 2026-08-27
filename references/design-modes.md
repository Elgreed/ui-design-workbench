# Generation and redesign modes

Choose one explicit `design.mode` before producing IR.

| Mode | Source of truth | Allowed creativity | Required fidelity status |
| --- | --- | --- | --- |
| `reconstruct` | Existing repository UI | None; report gaps separately | `translated` |
| `generate` | Product brief + project system + platform standards | Only reasoned choices within constraints | `designed` |
| `redesign` | Existing task flow/content + approved brief + standards | Improve named UX problems; preserve unrelated behavior | `designed` |

## Anti-randomness contract

Every visible or interactive decision must come from at least one of:

1. a literal project component, asset, token, or established pattern;
2. an official platform component or documented interaction pattern;
3. an explicit user/product requirement;
4. a `design.decisions` record with alternatives considered and a concrete UX reason.

Do not add gradients, glass effects, floating cards, oversized headings, novel navigation, decorative illustrations, animations, icon-only actions, or extra product copy merely to make a design look modern. If no product-specific visual direction exists, produce the restrained native baseline first.

## Design metadata

Generated and redesigned IR includes:

```json
{
  "design": {
    "mode": "redesign",
    "targetPlatforms": ["android", "ios", "web"],
    "brief": {
      "primaryTask": "Complete checkout with minimal uncertainty",
      "primaryUser": "Existing customer",
      "constraints": ["Preserve current fields", "No new backend data"]
    },
    "standardProfiles": {
      "android": {"id": "material3", "source": "official", "projectVersion": "from repository"},
      "ios": {"id": "apple-hig", "source": "official", "deploymentTarget": "from repository"},
      "web": {"id": "web-platform", "source": "WCAG 2.2 AA + APG"}
    },
    "decisions": [
      {
        "id": "decision-checkout-summary",
        "scope": "checkout/summary",
        "choice": "Keep order summary visible before confirmation",
        "basis": "user-task",
        "reason": "Reduces uncertainty before a consequential action",
        "alternatives": ["Collapsed summary"]
      }
    ],
    "stateMatrix": [
      {
        "screens": ["checkout"],
        "covered": ["default", "loading", "error", "disabled", "success", "destructive-confirmation"],
        "notApplicable": [
          {"state": "empty", "reason": "An empty cart cannot enter checkout."},
          {"state": "offline", "reason": "Handled by the shared network-error screen."},
          {"state": "permission", "reason": "No system permission is requested."}
        ]
      }
    ]
  },
  "fidelity": {"status": "designed", "sourceDerived": false}
}
```

Use a `project` standard profile only when the repository has an intentional component system. Include a `reason` describing the override. Do not call a collection of incidental styles a design system.

## Generate workflow

1. Inspect the repository for brand tokens, components, navigation architecture, localization, assets, dependencies, and supported platforms. If no repository exists, derive only the minimum product brief needed to proceed.
2. Define the primary task, user, content, data dependencies, constraints, success outcome, and target platforms. Separate known facts from assumptions.
3. Create the task flow and screen/state inventory before visual styling. Avoid adding screens that do not advance the task or satisfy a platform requirement.
4. Map each control and navigation container to the target platform profile. Add brand through shared semantic tokens, not per-screen decoration.
5. Design representative default, loading, empty, error, offline/permission, disabled, success, destructive-confirmation, and long-content states where applicable. Record non-applicable states with a reason.
6. Generate all screens, routes, transitions, focus behavior, and state actions in IR. Run the audit before presenting HTML.

## Redesign workflow

1. Reconstruct the current screen, task flow, content semantics, and states first. Preserve provenance to original files and symbols.
2. Write a short problem statement based on user feedback, explicit requirements, or observable heuristic violations. Do not redesign merely because a different style is possible.
3. Mark invariants: business rules, required fields, route contracts, analytics hooks, accessibility labels, data availability, and already accepted areas.
4. Create a native-baseline redesign that fixes the stated problems. Keep each changed region linked to a `decisionId`; unchanged regions remain source-linked.
5. Offer an additional variant only when it represents a meaningful tradeoff, not cosmetic randomness. State the tradeoff and keep content/functionality comparable.
6. Present the redesigned preview without editing project source. After approval, propose an implementation diff separately.

## Expert review workflow

An expert review is a staged reconstruction plus redesign, not a fourth rendering mode. First reconstruct the existing UI as the immutable baseline. Record evidence-based findings under `review.audit` using [ui-reviewer.md](ui-reviewer.md). Then set `design.mode: redesign` for correction versions and link each version to the findings it addresses. This keeps current-state fidelity separate from proposed design judgment.

Do not produce correction variants until the audit defines the problem, evidence, affected task, and preserved invariants. Do not treat a standards deviation as a defect when the repository documents an intentional, accessible project convention that serves the task.

## UX completeness gate

Before review, verify:

- clear primary task and visual hierarchy;
- predictable navigation, back/cancel behavior, and preserved context;
- feedback for taps, submissions, waiting, completion, and failure;
- prevention and recovery for destructive or costly actions;
- form labels, instructions, validation timing, error placement, and retained user input;
- empty/loading/error/offline/permission states where relevant;
- light/dark and text scaling where supported;
- keyboard/focus/assistive semantics and target sizes;
- resolvable foreground/background tokens that pass WCAG text-contrast thresholds in each reviewed theme;
- responsive/adaptive layouts, safe areas, RTL, localization expansion, and long content;
- no unsupported data, product copy, feature, or backend behavior invented by the design.

The HTML preview is evidence for review, not proof of runtime accessibility. Report which checks are structural and which still require platform testing after implementation.
