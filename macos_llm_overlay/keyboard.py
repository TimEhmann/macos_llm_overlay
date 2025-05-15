"""
Handles global keyboard event listening (hotkeys) and the UI for
setting a custom hotkey for the application.
"""
import json
import sys
import objc
import traceback
from AppKit import (
    NSView, NSColor, NSTextField, NSTextAlignmentCenter,
    NSFont, NSMakeRect, NSEvent, NSWindowAbove,
    NSViewWidthSizable, NSViewHeightSizable,
    NSViewMinXMargin, NSViewMaxXMargin, NSViewMinYMargin, NSViewMaxYMargin,
    NSTimer
)
from Foundation import NSObject
from Quartz import (
    CGEventGetIntegerValueField, kCGKeyboardEventKeycode, CGEventGetFlags,
    kCGEventKeyDown,
    kCGEventFlagMaskShift, kCGEventFlagMaskControl,
    kCGEventFlagMaskAlternate, kCGEventFlagMaskCommand
)

from macos_llm_overlay.config import TOGGLE_KEY, TOGGLE_KEY_MASK, TOGGLE_FILE

# Mapping of virtual keycodes to human-readable names for display purposes.
SPECIAL_KEY_NAMES = {
    0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C", 9: "V",
    11: "B", 12: "Q", 13: "W", 14: "E", 15: "R", 16: "Y", 17: "T",
    18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5", 24: "=", 25: "9", 26: "7",
    27: "-", 28: "8", 29: "0", 30: "]", 31: "O", 32: "U", 33: "[", 34: "I", 35: "P",
    36: "Return", 37: "L", 38: "J", 39: "'", 40: "K", 41: ";", 42: "\\", 43: ",",
    44: "/", 45: "N", 46: "M", 47: ".", 48: "Tab", 49: "Space", 50: "`", 51: "Delete",
    53: "Escape",
    122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7",
    100: "F8", 101: "F9", 109: "F10", 103: "F11", 111: "F12",
    123: "Left Arrow", 124: "Right Arrow", 125: "Down Arrow", 126: "Up Arrow",
    115: "Home", 119: "End", 116: "Page Up", 121: "Page Down", 71: "Clear"
}

# Global variable to hold the callback function during hotkey setup.
handle_new_toggle_callback = None

def load_custom_toggle_key():
    """
    Loads the custom hotkey combination (flags and keycode) from the
    JSON file specified in `TOGGLE_FILE` (config.py).
    Updates the global `TOGGLE_KEY` dictionary if a custom hotkey is found.
    """
    if TOGGLE_FILE.exists():
        try:
            with open(TOGGLE_FILE, "r") as f:
                data = json.load(f)
                # Update the global TOGGLE_KEY from config with loaded values
                TOGGLE_KEY.update({"flags": data["flags"], "key": data["key"]})
            print(f"Custom launcher toggle loaded: {TOGGLE_KEY}")
        except Exception as e:
            print(f"Error loading custom toggle from {TOGGLE_FILE}: {e}", file=sys.stderr)

def get_toggle_string(event, flags, keycode):
    """
    Generates a human-readable string representation of a key combination.
    Example: "Command + Shift + S"

    Args:
        event (CGEventRef): The CGEvent (used to derive characters for non-special keys).
        flags (int): The modifier flags (e.g., kCGEventFlagMaskCommand).
        keycode (int): The virtual keycode.

    Returns:
        str: A string describing the key combination.
    """
    modifiers = []
    if flags & kCGEventFlagMaskShift:
        modifiers.append("Shift")
    if flags & kCGEventFlagMaskControl:
        modifiers.append("Control")
    if flags & kCGEventFlagMaskAlternate:
        modifiers.append("Option")
    if flags & kCGEventFlagMaskCommand:
        modifiers.append("Command")

    key_name = SPECIAL_KEY_NAMES.get(keycode)

    if not key_name:
        # If keycode not in our special map, try to get character from NSEvent
        # This is a fallback for keys like letters, numbers, symbols not explicitly mapped.
        ns_event = NSEvent.eventWithCGEvent_(event)
        if ns_event:
            char = ns_event.charactersIgnoringModifiers()
            key_name = char.upper() if char and len(char) > 0 else f"Keycode {keycode}"
        else:
            key_name = f"Keycode {keycode}" # Fallback if NSEvent conversion fails
    
    return " + ".join(modifiers + [key_name])

class TargetSelectorWrapper(NSObject):
    """
    A simple Objective-C wrapper for a Python callable to be used as a target
    for NSTimer. NSTimer expects an Objective-C object and a selector.
    """
    _callback = objc.ivar()

    def initWithCallback_(self, callback):
        self = objc.super(TargetSelectorWrapper, self).init()
        if self is None: return None
        self._callback = callback
        return self
    
    @objc.IBAction
    def invoke(self, timer):
        """Called by NSTimer, invokes the stored Python callback."""
        if self._callback:
            self._callback()

def set_toggle_window(app_delegate):
    """
    Displays an overlay UI prompting the user to press a new key combination
    for the global hotkey. Handles capturing the new hotkey, saving it,
    and providing feedback.

    Args:
        app_delegate (OverlayAppDelegate): The main application delegate instance,
                                          used to access the main window and its views.
    """
    global handle_new_toggle_callback

    if not app_delegate.window:
        print("Error: Main window not available for setting toggle.", file=sys.stderr)
        return

    # Ensure the main window is visible and key to receive UI feedback.
    if not app_delegate.window.isVisible():
        app_delegate.showWindow_(None)
    app_delegate.window.makeKeyAndOrderFront_(None)

    print("Initiating launcher toggle configuration. Press Esc to cancel.", flush=True)
    
    # Store previous toggle in case of cancellation or error
    prev_toggle_flags = TOGGLE_KEY.get("flags")
    prev_toggle_key = TOGGLE_KEY.get("key")
    
    # Temporarily disable current hotkey by setting invalid values
    TOGGLE_KEY["flags"] = -1 
    TOGGLE_KEY["key"] = -1

    content_view = app_delegate.window.contentView()
    if not content_view:
        print("Error: Main window content view not available for setting toggle UI.", file=sys.stderr)
        # Restore previous toggle if UI setup fails
        TOGGLE_KEY["flags"] = prev_toggle_flags
        TOGGLE_KEY["key"] = prev_toggle_key
        return
        
    content_bounds = content_view.bounds()

    # --- UI Setup for "Set Hotkey" Dialog ---
    # Semi-transparent backdrop
    backdrop_view = NSView.alloc().initWithFrame_(content_bounds)
    backdrop_view.setWantsLayer_(True)
    backdrop_view.layer().setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.5, 0.5).CGColor()) # Dark semi-transparent
    backdrop_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable) # Fill parent

    # Dialog box
    dialog_width = 420
    dialog_height = 200
    dialog_x = (content_bounds.size.width - dialog_width) / 2
    dialog_y = (content_bounds.size.height - dialog_height) / 2
    dialog_frame = NSMakeRect(dialog_x, dialog_y, dialog_width, dialog_height)
    dialog_box = NSView.alloc().initWithFrame_(dialog_frame)
    dialog_box.setWantsLayer_(True)
    dialog_box.layer().setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.2, 0.9).CGColor()) # Darker, mostly opaque
    dialog_box.layer().setCornerRadius_(15)
    # Center dialog box if window resizes (though unlikely during this modal operation)
    dialog_box.setAutoresizingMask_(NSViewMinXMargin | NSViewMaxXMargin | NSViewMinYMargin | NSViewMaxYMargin)

    # Instruction text
    message_text = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 60, dialog_width - 40, 80))
    message_text.setStringValue_("Press the new toggle key combination.\n(Press Escape to cancel)")
    message_text.setFont_(NSFont.systemFontOfSize_(16))
    message_text.setTextColor_(NSColor.whiteColor())
    message_text.setAlignment_(NSTextAlignmentCenter)
    message_text.setDrawsBackground_(False)
    message_text.setBezeled_(False)
    message_text.setEditable_(False)
    message_text.setSelectable_(False)

    dialog_box.addSubview_(message_text)
    backdrop_view.addSubview_(dialog_box)
    # Add backdrop on top of existing content view's subviews
    content_view.addSubview_positioned_relativeTo_(backdrop_view, NSWindowAbove, None)

    def new_toggle_handler_inner(event, flags, keycode):
        """
        This inner function becomes the temporary event handler when setting a new hotkey.
        It's assigned to `handle_new_toggle_callback`.
        """
        nonlocal prev_toggle_flags, prev_toggle_key
        global handle_new_toggle_callback

        if keycode == 53:  # Escape key (keycode 53)
            print("Hotkey configuration aborted by user (Escape pressed).", flush=True)
            message_text.setStringValue_("Operation cancelled. Reverted to previous hotkey.")
            # Restore previous hotkey
            TOGGLE_KEY["flags"] = prev_toggle_flags
            TOGGLE_KEY["key"] = prev_toggle_key
        else:
            # A new hotkey combination was pressed
            updated_toggle = {"flags": flags, "key": keycode}
            try:
                # Save the new hotkey to the JSON file
                with open(TOGGLE_FILE, "w") as f:
                    json.dump(updated_toggle, f)
                TOGGLE_KEY.update(updated_toggle)
                toggle_str = get_toggle_string(event, flags, keycode)
                print(f"Launcher toggle updated to: {toggle_str}", flush=True)
                message_text.setStringValue_(f"New hotkey set:\n{toggle_str}")
            except Exception as e:
                print(f"Failed to save new hotkey configuration to {TOGGLE_FILE}: {e}", file=sys.stderr)
                message_text.setStringValue_("Error saving hotkey! Reverted.")
                # Restore previous hotkey on error
                TOGGLE_KEY["flags"] = prev_toggle_flags
                TOGGLE_KEY["key"] = prev_toggle_key

        # --- Cleanup UI and reset state ---
        def remove_overlay_and_reset():
            global handle_new_toggle_callback
            if backdrop_view and backdrop_view.superview():
                backdrop_view.removeFromSuperview()
            handle_new_toggle_callback = None # Crucial: reset event tap to normal operation
            print(f"Hotkey configuration UI dismissed. Current hotkey: {TOGGLE_KEY}", flush=True)
            # Return focus to webView if possible
            if app_delegate and app_delegate.window and app_delegate.webView:
                app_delegate.window.makeFirstResponder_(app_delegate.webView)

        # Schedule the UI removal and state reset after a short delay to show the message
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, # delay in seconds
            TargetSelectorWrapper.alloc().initWithCallback_(remove_overlay_and_reset),
            "invoke", # Selector defined in TargetSelectorWrapper
            None,     # userInfo
            False     # repeats: No
        )
        return None

    # Set the global callback to our inner handler.
    # The main event tap listener will now call this function for key down events.
    handle_new_toggle_callback = new_toggle_handler_inner

def global_toggle_listener(app_shim_instance):
    """
    Creates and returns the callback function for the global event tap.
    This callback handles the global hotkey to toggle the app window
    and also defers to `handle_new_toggle_callback` if a new hotkey is being set.

    Args:
        app_shim_instance: An instance of AppEventTapShim, used to interact
                           with the main application delegate for UI updates.

    Returns:
        A callable suitable for use as a CGEventTapCallBack.
    """
    def tap_event_callback(proxy, type, event, refcon):
        global handle_new_toggle_callback # To check and call if active

        try:
            # We are interested in KeyDown events
            if type == kCGEventKeyDown:
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                flags = CGEventGetFlags(event)
                
                # Mask the event flags to only include standard modifiers we care about
                # (Shift, Control, Option, Command) as defined in TOGGLE_KEY_MASK.
                # This ensures that other flags (like Caps Lock) don't interfere
                # with hotkey matching unless explicitly part of the saved TOGGLE_KEY["flags"].
                current_event_modifier_flags = flags & TOGGLE_KEY_MASK

                # If 'set_toggle_window' is active, it sets 'handle_new_toggle_callback'.
                if handle_new_toggle_callback:
                    handle_new_toggle_callback(event, current_event_modifier_flags, keycode)
                    return None

                # Normal operation: check if the pressed key matches the global TOGGLE_KEY
                if ("key" in TOGGLE_KEY and TOGGLE_KEY.get("key") != -1 and
                    "flags" in TOGGLE_KEY and
                    keycode == TOGGLE_KEY["key"] and
                    current_event_modifier_flags == TOGGLE_KEY["flags"]):
                    
                    # print(f"DEBUG: Global hotkey matched: Code={keycode}, Flags={current_event_modifier_flags}", file=sys.stderr)
                    
                    if app_shim_instance and \
                       hasattr(app_shim_instance, '_delegate_instance') and \
                       app_shim_instance._delegate_instance and \
                       hasattr(app_shim_instance._delegate_instance, 'toggleWindowVisibility_'):
                        
                        app_shim_instance._delegate_instance.performSelectorOnMainThread_withObject_waitUntilDone_(
                            'toggleWindowVisibility:',
                            None,
                            False
                        )
                        return None
            
            return event
        
        except Exception as e:
            # Log any exception that occurs within the callback to avoid silent failures
            # and ensure the event tap doesn't get stuck.
            print(f"CRITICAL ERROR in global_toggle_listener callback: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            return event # Essential to return the event, even on error, to avoid blocking all input

    return tap_event_callback
