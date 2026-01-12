# Viewer Hooks

Viewer hooks are discovered through the `brkraw.viewer.hook` entry point group.
Each hook can provide a tab UI and dataset callbacks.

Hooks exist to keep the core viewer small while enabling modality-specific
panels that reuse BrkRaw's rule/spec system. Viewer hooks can coexist with
converter hooks and CLI hooks, so UI features can build on the same conversion
logic without patching the viewer itself.

## Entry point

Add an entry point in your `pyproject.toml`:

```toml
[project.entry-points."brkraw.viewer.hook"]
brkraw-mrs = "brkraw_mrs.viewer_hook:MRSViewerHook"
```

## Hook interface

Hooks may implement any of the following methods:

```python
class MyHook:
    name = "my-extension"
    priority = 0

    def build_tab(self, parent, app):
        ...

    def on_dataset_loaded(self, app):
        ...

    def on_scan_selected(self, app):
        ...
```
