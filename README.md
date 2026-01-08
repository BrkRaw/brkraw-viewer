# BrkRaw Viewer

BrkRaw Viewer is an interactive dataset viewer implemented as a
separate CLI plugin for the `brkraw` command.

The viewer is intentionally maintained outside the BrkRaw core to
enable independent development and community contributions around
user-facing interfaces.

A redesigned interface is planned. The current implementation
started from functionality in earlier BrkRaw versions and is
now evolving into a more complete, extensible viewer.

---

## Scope and intent

BrkRaw Viewer is designed for **interactive inspection** of Bruker
Paravision datasets. It focuses on quick exploration and validation
rather than data conversion or analysis.

The goal is to provide practical, researcher-focused features that are
useful in everyday workflows, such as quick dataset triage, metadata
checks, and lightweight visual QC.

Typical use cases include:

- Browsing studies, scans, and reconstructions
- Verifying scan and reconstruction IDs
- Inspecting acquisition metadata before conversion
- Lightweight visual sanity checks

All data conversion and reproducible workflows are handled by the
BrkRaw CLI and Python API.

---

## Design goal: shared extensibility

The primary goal of brkraw-viewer is to **share and reuse the full
extensibility model of the BrkRaw core**.

The viewer is designed to work with the same rules, specs, layouts,
and converter hooks used by the BrkRaw CLI and Python API. Newly
installed hooks should become naturally available to the viewer
without additional glue code.

This includes support for modality-specific hooks, such as
MRS-related extensions, where modality-aware viewers can be built
by consuming metadata and outputs already provided by the core
extension system.

---

## UI direction

The default viewer targets a **tkinter-based** implementation.

This choice is intentional: we want a lightweight tool that can be
used directly on scanner consoles or constrained environments with
minimal dependencies.

More modern GUI frameworks are welcome, but should be developed as
separate CLI extensions to keep the default viewer small and easy to
install.

---

## Viewer extension ideas

In addition to sharing BrkRaw core extensibility, we are exploring a
viewer-focused extension model for user interfaces.

Possible directions include:

- A "viewer plugin" registry that discovers optional UI modules
  (e.g. modality panels such as an MRS viewer)
- A small set of stable UI contracts (panels, renderers, inspectors)
  that can be extended without changing the core viewer
- Hook-aware UI components that activate automatically when relevant
  converter hooks are installed

The goal is to keep the default viewer minimal while still enabling
richer interfaces through optional extensions.

---

## Installation

For development and testing, install in editable mode:

    pip install -e .

---

## Usage

Launch the viewer via the BrkRaw CLI:

    brkraw viewer /path/to/bruker/study

Optional arguments allow opening a specific scan or slice:

    brkraw viewer /path/to/bruker/study \
        --scan 3 \
        --reco 1 \
        --axis axial \
        --slice 20

The viewer can also open `.zip` or Paravision-exported `.PvDatasets`
archives using `Load` (folder or archive file).

---

## Project status

- Interface redesign: planned
- Current viewer: expanding feature set
- Default UI target: tkinter with minimal dependencies
- Extension model: shared with BrkRaw core
- Contribution model: open and experimental

---

## Update

Recent updates:

- Open folders or archives (`.zip` / `.PvDatasets`)
- Viewer: `Space` (`raw/scanner/subject_ras`), nibabel RAS display, click-to-set `X/Y/Z`, optional crosshair + zoom, slicepack/frame sliders only when needed
- Info: rule + spec selection (installed or file override), parameter search, lazy Viewer refresh on tab focus
- Convert: BrkRaw layout engine, template + suffix defaults from `~/.brkraw/config.yaml`, keys browser (click to add), optional config `layout_entries`
- Config: edit `~/.brkraw/config.yaml` in-app; basic focus/icon UX

This update keeps dependencies minimal and preserves compatibility with
the core BrkRaw rule/spec/hook system.

---

## Contributing

This repository is intentionally published as an evolving prototype.

We welcome contributions related to:

- Lightweight graphical or interactive interfaces
- tkinter UI improvements and scanner-console friendly workflows
- Researcher-focused everyday features (triage, metadata checks, QC)
- Visualization of BrkRaw rules, specs, and layout behavior
- Interactive inspection of metadata produced by converter hooks
- Modality-specific viewers built on shared hooks (e.g. MRS viewers)
- fMRI-oriented visualization and preprocessing helpers
- BIDS-oriented dataset browsing and validation helpers
- Handling and browsing multiple datasets in a single session

Contributions should prefer designs where new hooks extend the viewer
implicitly through shared BrkRaw abstractions, and where richer UIs are
provided as optional CLI extensions rather than increasing the default
dependency footprint.

If you are interested in contributing, please start a discussion or
open an issue describing your use case and goals.
