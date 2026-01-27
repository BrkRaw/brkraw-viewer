from .window import ExtensionsTab

TITLE = ExtensionsTab.TITLE


def build(parent, callbacks):
    return ExtensionsTab(parent, callbacks).frame
