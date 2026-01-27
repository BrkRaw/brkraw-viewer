from .window import ParamsTab

TITLE = ParamsTab.TITLE


def build(parent, callbacks):
    return ParamsTab(parent, callbacks).frame
