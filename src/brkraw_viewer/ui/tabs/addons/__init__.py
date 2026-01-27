from .window import AddonsTab

TITLE = AddonsTab.TITLE


def build(parent, callbacks):
    return AddonsTab(parent, callbacks).frame
