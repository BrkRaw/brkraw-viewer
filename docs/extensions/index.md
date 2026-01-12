# Extensions

Extensions exist so the default viewer can stay lightweight while specialized
workflows (MRS, BIDS, etc.) live in their own packages. This keeps the GUI
small for scanner environments but still lets teams build richer interfaces.

BrkRaw Viewer supports optional extensions via Python entry points. Extensions
can add a tab and dataset-specific UI.

## Installing extensions

Install the extension package in the same environment as `brkraw-viewer`:

```bash
pip install brkraw-mrs
```

## Selecting an extension

Extensions are selected manually in the **Extensions** tab. The default value
is **None**, which keeps the core viewer active.

The `brkraw-mrs` extension renders its underlay preview inside the MRS tab to
keep the core viewer stable. Underlay controls live in the MRS tab alongside
the spectrum view.
