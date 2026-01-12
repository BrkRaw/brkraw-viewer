# Brkraw Viewer

BrkRaw Viewer is a lightweight GUI for browsing and inspecting Bruker datasets
with a focus on stability and a clean separation between the core viewer and
optional extensions.

Its intent is simple: **keep inspection fast and local**, while delegating
repeatable workflows to the brkraw CLI and extension ecosystem.

## Highlights

- Load Bruker study folders, archives, or PvDatasets packages
- Inspect scan metadata and parameter tables
- Preview image volumes with orientation controls
- Convert datasets with configurable naming/layout
- Optional extensions via entry points (no core edits required)

## Why these features exist

**Viewer**
The Viewer tab gives quick visual confirmation of orientation and scan content
so researchers can make decisions before running heavier pipelines.

**Registry**
The Registry exists to reduce repetitive filesystem navigation. It stores
datasets you care about and lets you reload the current session in one click.

**Extensions/hooks**
Extensions allow modality-specific UI (MRS, BIDS, etc.) without inflating the
default dependency set. Hooks share the same rule/spec system as brkraw so the
viewer stays aligned with core workflows.

## Getting started

Install the package and run:

```bash
brkraw viewer
```

The main tabs are Viewer, Info, Convert, and Config. Extensions are available
under the Extensions tab and are selected manually.
