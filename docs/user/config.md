# Config

The Config tab keeps **viewer defaults in one place** so teams can align on
layout and registry preferences without editing YAML by hand.

## Common settings

- Viewer display options
- Column layout for registry tables
- Conversion layout defaults
- Viewer cache settings (memory-only, cleared on exit)

Changes are written to `config.yaml` and applied at the next load.

For one-off external registry files, use CLI output override:

`brkraw viewer-registry add <path> -t /path/to/registry`
