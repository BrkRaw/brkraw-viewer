from .window import ConfigTab

TITLE = ConfigTab.TITLE


def build(parent, callbacks):
    return ConfigTab(parent, callbacks).frame
