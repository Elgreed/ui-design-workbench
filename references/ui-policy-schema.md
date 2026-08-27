# Project UI policy

An optional `.codex/ui-policy.json` makes design choices repeatable across tasks. Do not create or change it inside a repository without explicit approval. `ui-policy.json` at the repository root is also recognized.

```json
{
  "version": 1,
  "platforms": {
    "android": {
      "standardProfile": "material3",
      "implementation": "compose",
      "allowExperimental": false,
      "minimumTarget": 48,
      "adaptive": true
    },
    "ios": {
      "standardProfile": "apple-hig",
      "implementation": "swiftui",
      "minimumTarget": 44,
      "preferSystemComponents": true
    },
    "web": {
      "standardProfile": "web-platform",
      "wcagTarget": "2.2 AA",
      "minimumTarget": 24,
      "preferNativeHtml": true
    }
  },
  "brand": {
    "tokenSources": ["design/tokens.json"],
    "componentRoots": ["ui/components"],
    "assetRoots": ["assets"],
    "allowInventedCopy": false
  },
  "rules": {
    "preferProjectComponents": true,
    "allowNewDependencies": false,
    "allowCrossPlatformVisualParity": false,
    "requireStateMatrix": true,
    "forbiddenPatterns": [
      "unapproved gradients",
      "decorative glass effects",
      "icon-only destructive actions",
      "navigation controls used as actions"
    ]
  }
}
```

## Resolution

- Explicit user instructions override the policy for the current task; record the override.
- Repository instructions and installed framework constraints remain authoritative for implementation.
- Missing policy values fall back to [platform-standards.md](platform-standards.md), not to model preference.
- Numeric minimums may be stricter than platform defaults but must not be weaker than required accessibility baselines without a documented standards exception.
- Paths are repository-relative. The policy identifies authoritative sources; it does not duplicate token or component contents.

Copy the resolved policy into `design.policySnapshot` in review IR. Include `policyFile` so annotations and later tasks can trace the decision source. Never silently mutate the policy during preview iteration.
