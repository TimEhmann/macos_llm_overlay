from AppKit import NSWindow, NSView, NSApp, NSEventModifierFlagCommand

class AppWindow(NSWindow):
    """
    A custom NSWindow subclass that allows for a borderless window with a transparent background.
    This window can be dragged around the screen by clicking and dragging the top bar.
    """

    def canBecomeKeyWindow(self):
        return True

    def keyDown_(self, event):
        self.delegate().keyDown_(event)

class DragArea(NSView):
    """
    A custom NSView subclass that enables window dragging when clicked.
    This is used for the top bar of the borderless window.
    """
    def mouseDown_(self, event):
        self.window().performWindowDragWithEvent_(event)
