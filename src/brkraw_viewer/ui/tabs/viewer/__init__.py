from .window import ViewerTab

TITLE = ViewerTab.TITLE


def build(parent, callbacks):
    return ViewerTab(parent, callbacks).frame
