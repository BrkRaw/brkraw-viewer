from .window import ConvertTab

TITLE = ConvertTab.TITLE


def build(parent, callbacks):
    return ConvertTab(parent, callbacks).frame
