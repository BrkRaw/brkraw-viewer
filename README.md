# BrkRaw Viewer

BrkRaw scan viewer plugin for the `brkraw` CLI entry point.

## Install (editable)

```bash
pip install -e .
```

## Usage

```bash
brkraw viewer /path/to/bruker/study
```

Optional flags:

```bash
brkraw viewer /path/to/bruker/study --scan 3 --reco 1 --axis axial --slice 20
```

The GUI can also open `.zip` datasets via the "Open File" button.

Optional override for scan info spec:

```bash
brkraw viewer /path/to/bruker/study --info-spec /path/to/scan.yaml
```
