"""
Main application module for the macOS LLM Overlay.
This module sets up the application, creates the overlay window,
manages the WebView, handles global hotkeys, and defines the
application lifecycle.
"""
import os
import sys
import objc # PyObjC bridge
from AppKit import * # Cocoa framework
from WebKit import * # WebKit framework for WKWebView
from Quartz import * # Core Graphics framework for event taps, etc.
from Foundation import * # Foundation framework for NSObject, NSApplication, etc.

from macos_llm_overlay.config import * # Application configuration
from macos_llm_overlay.window import AppWindow, DragArea
from macos_llm_overlay.keyboard import load_custom_toggle_key, set_toggle_window, global_toggle_listener
from macos_llm_overlay.utils import check_permissions, crash_logger


class AppEventTapShim(NSObject):
    """
    A shim object to bridge the C-style CGEventTap callback with the
    Objective-C based OverlayAppDelegate instance. The CGEventTap callback
    needs a C function pointer, which can't directly call methods on an
    Objective-C instance in a straightforward way with PyObjC's callback mechanisms.
    This shim holds a reference to the delegate and exposes Objective-C methods
    that the Python callback function (created by global_toggle_listener) can call.
    """
    _delegate_instance = objc.ivar() # Holds the OverlayAppDelegate instance

    def initWithDelegate_(self, delegate_instance):
        self = objc.super(AppEventTapShim, self).init()
        if self is None:
            return None
        self._delegate_instance = delegate_instance
        return self

    def window(self):
        """Provides access to the main window via the delegate."""
        if self._delegate_instance:
            return self._delegate_instance.window
        return None

    @objc.IBAction
    def hideWindow_(self, sender):
        """Relays the hideWindow action to the delegate."""
        if self._delegate_instance:
            self._delegate_instance.hideWindow_(sender)

    @objc.IBAction
    def showWindow_(self, sender):
        """Relays the showWindow action to the delegate."""
        if self._delegate_instance:
            self._delegate_instance.showWindow_(sender)

class OverlayAppDelegate(NSObject):
    """
    The main application delegate. Handles application lifecycle events,
    manages the main window, WebView, status bar item, and global event tap.
    """
    # --- Instance Variables (ivars) for Objective-C ---
    window = objc.ivar()      # The main application window (NSWindow)
    webView = objc.ivar()     # The WebView displaying the content (WKWebView)
    contentView = objc.ivar() # The main content view of the window (NSView)
    dragArea = objc.ivar()    # The custom draggable area (DragArea)
    statusItem = objc.ivar()  # The status bar item (NSStatusItem)
    
    eventTap = objc.ivar()        # The CGEventTap for global hotkeys
    tap_callback_ref = objc.ivar() # Reference to the Python callback for the event tap
    app_shim = objc.ivar()        # Instance of AppEventTapShim
    currentProviderName = objc.ivar() # Name of the currently selected LLM provider
    providerMenu = objc.ivar()    # Submenu for provider selection

    def applicationDidFinishLaunching_(self, notification):
        """
        Called when the application has finished launching.
        This is where the main setup occurs.
        """
        app = NSApplication.sharedApplication()
        # Set as an accessory application: no Dock icon, no main menu bar by default.
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        # Check and request Accessibility Permissions for global hotkey
        initial_permissions_granted = check_permissions(ask=False)
        self.eventTap = None # Initialize eventTap

        if not initial_permissions_granted:
            print("INFO: Accessibility permissions not yet granted. Requesting now...")
            if check_permissions(ask=True): # Prompt user for permissions
                print("INFO: Accessibility permissions granted in this session. The global hotkey *should* now work. If not, please restart the application.")
            else:
                print("WARNING: Accessibility permissions were NOT granted. Global hotkey will NOT work.")
        else:
            print("INFO: Accessibility permissions were already granted.")

        # --- Window Setup ---
        screen_rect = NSScreen.mainScreen().frame()
        # Load saved window frame or use default
        saved_frame_str = NSUserDefaults.standardUserDefaults().stringForKey_(FRAME_SAVE_NAME)
        if saved_frame_str:
            window_rect = NSRectFromString(saved_frame_str)
        else:
            window_rect = NSMakeRect(
                (screen_rect.size.width - INITIAL_WIDTH) / 2,
                (screen_rect.size.height - INITIAL_HEIGHT) / 2,
                INITIAL_WIDTH,
                INITIAL_HEIGHT
            )

        self.window = AppWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            window_rect,
            NSWindowStyleMaskBorderless | NSWindowStyleMaskResizable, # Borderless, resizable window
            NSBackingStoreBuffered,
            False
        )
        self.window.setLevel_(NSFloatingWindowLevel) # Keep window above most others
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | # Visible on all Spaces
            NSWindowCollectionBehaviorStationary |      # Doesn't move with Spaces
            NSWindowCollectionBehaviorFullScreenAuxiliary # Can be shown over full-screen apps
        )
        self.window.setReleasedWhenClosed_(False) # Don't deallocate window when closed, just hide
        self.window.setDelegate_(self)            # Set this class as the window's delegate
        self.window.setOpaque_(False)             # Allow transparency
        self.window.setBackgroundColor_(NSColor.clearColor()) # Transparent background

        # --- Custom Content View with Rounded Corners ---
        content_view_frame = self.window.contentView().bounds()
        self.contentView = NSView.alloc().initWithFrame_(content_view_frame)
        self.contentView.setWantsLayer_(True) # Enable layer-backing for rounded corners, etc.
        if self.contentView.layer():
            self.contentView.layer().setCornerRadius_(DRAG_AREA_HEIGHT / 2) # Rounded top corners effect
            self.contentView.layer().setBackgroundColor_(NSColor.whiteColor().CGColor()) # Background for webview content
            self.contentView.layer().setMasksToBounds_(True) # Clip subviews to rounded corners
        self.contentView.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.window.setContentView_(self.contentView)

        # --- Draggable Area (Top Bar) ---
        drag_area_frame = NSMakeRect(
            0,
            self.contentView.bounds().size.height - DRAG_AREA_HEIGHT, # Position at the top
            self.contentView.bounds().size.width,
            DRAG_AREA_HEIGHT
        )
        self.dragArea = DragArea.alloc().initWithFrame_(drag_area_frame)
        self.dragArea.setBackgroundColor_(NSColor.darkGrayColor()) # Visible drag bar
        self.dragArea.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin) # Resize with window
        self.contentView.addSubview_(self.dragArea)

        # --- Close Button ---
        close_button_size = DRAG_AREA_HEIGHT * 0.75
        close_button_margin = (DRAG_AREA_HEIGHT - close_button_size) / 2
        close_button_frame = NSMakeRect(
            close_button_margin,
            close_button_margin,
            close_button_size,
            close_button_size
        )
        closeButton = NSButton.buttonWithTitle_target_action_("✕", self, "hideWindow:")
        closeButton.setFrame_(close_button_frame)
        closeButton.setBezelStyle_(NSBezelStyleRegularSquare) # Simple style
        closeButton.setBordered_(False)
        closeButton.setFont_(NSFont.systemFontOfSize_(14))
        closeButton.setAutoresizingMask_(NSViewMaxXMargin | NSViewMinYMargin) # Pin to top-left
        self.dragArea.addSubview_(closeButton)
        
        # --- WebView Setup ---
        webViewConfig = WKWebViewConfiguration.alloc().init()
        if webViewConfig.preferences(): # Ensure preferences exist
            webViewConfig.preferences().setJavaScriptCanOpenWindowsAutomatically_(True)

        web_view_frame = NSMakeRect(
            0,
            0, # Position below drag area
            self.contentView.bounds().size.width,
            self.contentView.bounds().size.height - DRAG_AREA_HEIGHT # Fill remaining space
        )
        self.webView = WKWebView.alloc().initWithFrame_configuration_(web_view_frame, webViewConfig)
        # Set a common user agent to avoid compatibility issues with websites.
        self.webView.setCustomUserAgent_("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")
        self.webView.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable) # Resize with window
        # Add webView below the dragArea so dragArea is always on top
        self.contentView.addSubview_positioned_relativeTo_(self.webView, NSWindowBelow, self.dragArea)

        # --- Load Current Provider ---
        saved_provider = NSUserDefaults.standardUserDefaults().stringForKey_(CURRENT_PROVIDER_KEY)
        if saved_provider and saved_provider in PROVIDER_URLS:
            self.currentProviderName = saved_provider
        else:
            self.currentProviderName = DEFAULT_PROVIDER_NAME

        initial_url_string = PROVIDER_URLS.get(self.currentProviderName)
        if initial_url_string:
            self._loadURLString_(initial_url_string)
        else:
            print(f"ERROR: Default provider URL for '{self.currentProviderName}' not found.", file=sys.stderr)

        # --- Status Bar Item Setup ---
        self.statusItem = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        # Load icon for status bar
        icon_image = NSImage.alloc().initByReferencingFile_(ICON_PATH)
        if icon_image and icon_image.isValid():
            icon_image.setSize_((18, 18)) # Standard status bar icon size
            icon_image.setTemplate_(True)  # Allows macOS to style it (e.g., dark mode)
            self.statusItem.button().setImage_(icon_image)
        else:
            self.statusItem.button().setTitle_("LLM") # Fallback text
            print(f"Warning: Could not load icon from {ICON_PATH}")

        # --- Status Bar Menu ---
        statusMenu = NSMenu.alloc().init()
        
        # Menu item to toggle window visibility (using Command+Space as a visual cue, not the actual hotkey)
        toggleMenuItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Toggle " + APP_TITLE, "toggleWindowVisibility:", " ") 
        toggleMenuItem.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand) # Makes Cmd+Space show in menu
        toggleMenuItem.setTarget_(self)
        statusMenu.addItem_(toggleMenuItem)

        # --- Change Provider Submenu ---
        self.providerMenu = NSMenu.alloc().init()
        changeProviderMenuItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Change Provider", None, "")

        for provider_name in PROVIDER_URLS.keys():
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(provider_name, "changeProvider:", "")
            item.setTarget_(self)
            self.providerMenu.addItem_(item)

        changeProviderMenuItem.setSubmenu_(self.providerMenu)
        statusMenu.addItem_(changeProviderMenuItem)
        self._updateProviderMenuChecks() # Set initial checkmark

        # Menu item to open the "Set Hotkey" dialog
        setToggleMenuItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Set Toggle Hotkey...", "openSetToggleWindow:", "")
        setToggleMenuItem.setTarget_(self)
        statusMenu.addItem_(setToggleMenuItem)
        
        statusMenu.addItem_(NSMenuItem.separatorItem()) # Separator
        
        # Menu item to quit the application
        quitMenuItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit " + APP_TITLE, "terminate:", "q")
        statusMenu.addItem_(quitMenuItem)
        
        self.statusItem.setMenu_(statusMenu)

        # --- Global Hotkey (Event Tap) Setup ---
        self.app_shim = AppEventTapShim.alloc().initWithDelegate_(self)
        
        load_custom_toggle_key() # Load user-defined hotkey if it exists
        # Get the Python callback function for the event tap
        self.tap_callback_ref = global_toggle_listener(self.app_shim)

        # Create the actual CGEventTap
        self.eventTap = CGEventTapCreate(
            kCGSessionEventTap,      # Listen to system-wide events
            kCGHeadInsertEventTap,   # Insert tap at the head of the event stream
            kCGEventTapOptionDefault, # Default behavior for the tap
            CGEventMaskBit(kCGEventKeyDown), # Listen for key down events
            self.tap_callback_ref,   # The callback function
            None                     # User data (not used here)
        )

        if not self.eventTap:
            print("ERROR: Failed to create CGEventTap. Global hotkey will NOT work.")
            if not check_permissions(ask=False): # Re-check permissions if tap creation fails
                print("ERROR: Accessibility permissions are likely still missing or were denied.")
            else:
                print("ERROR: Event tap creation failed even with permissions. Other issue might be present (e.g., another app has exclusive tap).")
        else:
            # Add the event tap to the current run loop to receive events
            runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, self.eventTap, 0)
            CFRunLoopAddSource(CFRunLoopGetCurrent(), runLoopSource, kCFRunLoopCommonModes)
            CGEventTapEnable(self.eventTap, True) # Enable the event tap
            print(f"INFO: Global hotkey listener enabled. Current Toggle: {TOGGLE_KEY}")

        self.showWindow_(None) # Show the window on launch

    def _loadURLString_(self, url_string):
        """Helper to load a URL string into the webView."""
        url = NSURL.URLWithString_(url_string)
        request = NSURLRequest.requestWithURL_(url)
        self.webView.loadRequest_(request)

    @objc.IBAction
    def showWindow_(self, sender):
        """Shows the main application window."""
        if self.window:
            if not self.window.isVisible():
                # Restore previous frame if available, otherwise it uses its current frame (set during init)
                saved_frame_str = NSUserDefaults.standardUserDefaults().stringForKey_(FRAME_SAVE_NAME)
                if saved_frame_str:
                    self.window.setFrame_display_(NSRectFromString(saved_frame_str), True)

            self.window.makeKeyAndOrderFront_(None) # Bring to front and make key window
            NSApp.activateIgnoringOtherApps_(True)   # Ensure app becomes active
            self.window.makeFirstResponder_(self.webView) # Focus the webview for input

    @objc.IBAction
    def hideWindow_(self, sender):
        """Hides the main application window and saves its frame."""
        if self.window and self.window.isVisible():
            # Save current window frame (position and size)
            NSUserDefaults.standardUserDefaults().setObject_forKey_(
                NSStringFromRect(self.window.frame()), # Convert NSRect to NSString for saving
                FRAME_SAVE_NAME
            )
            NSUserDefaults.standardUserDefaults().synchronize() # Ensure data is written
            self.window.orderOut_(None) # Hide the window

    @objc.IBAction
    def toggleWindowVisibility_(self, sender):
        """Toggles the visibility of the main window."""
        if self.window.isVisible():
            self.hideWindow_(None)
        else:
            self.showWindow_(None)

    @objc.IBAction
    def openSetToggleWindow_(self, sender):
        """Initiates the UI for setting a new global hotkey."""
        set_toggle_window(self) # Calls the function from keyboard.py
        print("INFO: 'Set New Global Hotkey' initiated.")
    
    @objc.IBAction
    def changeProvider_(self, sender):
        """Handles selection of a new LLM provider from the menu."""
        new_provider_name = sender.title()
        if new_provider_name in PROVIDER_URLS:
            self.currentProviderName = new_provider_name
            NSUserDefaults.standardUserDefaults().setObject_forKey_(self.currentProviderName, CURRENT_PROVIDER_KEY)
            NSUserDefaults.standardUserDefaults().synchronize()

            url_to_load = PROVIDER_URLS[self.currentProviderName]
            self._loadURLString_(url_to_load)
            print(f"Changed provider to: {self.currentProviderName}, loading: {url_to_load}")
            self._updateProviderMenuChecks()
        else:
            print(f"Error: Unknown provider selected '{new_provider_name}'", file=sys.stderr)

    def _updateProviderMenuChecks(self):
        """Updates checkmarks in the provider selection submenu."""
        if self.providerMenu and self.currentProviderName:
            for item in self.providerMenu.itemArray():
                is_current = (item.title() == self.currentProviderName)
                item.setState_(NSOnState if is_current else NSOffState)

    # --- NSWindowDelegate Methods ---
    def windowShouldClose_(self, sender):
        """Called when the window's close button (if it had one) is clicked."""
        self.hideWindow_(None) # Hide instead of closing
        return False # Prevent actual closing

    def windowDidResize_(self, notification):
        """Called after the window has been resized. Save the new frame."""
        if self.window:
            NSUserDefaults.standardUserDefaults().setObject_forKey_(
                NSStringFromRect(self.window.frame()),
                FRAME_SAVE_NAME
            )
            NSUserDefaults.standardUserDefaults().synchronize()

    def windowDidMove_(self, notification):
        """Called after the window has been moved. Save the new frame."""
        if self.window:
            NSUserDefaults.standardUserDefaults().setObject_forKey_(
                NSStringFromRect(self.window.frame()),
                FRAME_SAVE_NAME
            )
            NSUserDefaults.standardUserDefaults().synchronize()
    
    def windowWillClose_(self, notification):
        """
        Called when the window is about to be closed (e.g., during app termination).
        Perform cleanup here.
        """
        # Disable and release the event tap
        if self.eventTap:
            CGEventTapEnable(self.eventTap, False)
            # CFMachPortInvalidate(self.eventTap) # Invalidate the mach port
            # CFRelease(self.eventTap) # Release the tap reference. Note: PyObjC might handle some CF object releases.
            self.eventTap = None # Clear the reference
            print("Global event tap disabled.")
        
        # Save window state one last time
        if self.window and self.window.isVisible():
             NSUserDefaults.standardUserDefaults().setObject_forKey_(
                NSStringFromRect(self.window.frame()),
                FRAME_SAVE_NAME
            )
        NSUserDefaults.standardUserDefaults().synchronize()
        print("Window state saved before closing.")

    def applicationWillTerminate_(self, notification):
        """Called when the application is about to terminate."""
        print("Application will terminate.")
        self.windowWillClose_(notification) # Perform window cleanup
        if self.app_shim: # Clear shim reference
            self.app_shim = None

    def keyDown_(self, event):
        modifiers = event.modifierFlags()
        key_command = modifiers & NSEventModifierFlagCommand
        key = event.charactersIgnoringModifiers()
        if key_command and key == 'q':
            NSApp.terminate_(None)
        elif key == 'c':
            self.window.firstResponder().copy_(None)
        elif key == 'v':
            self.window.firstResponder().paste_(None)
        if key == 'a':
            self.window.firstResponder().selectAll_(None)
        elif key == 'x':
            self.window.firstResponder().cut_(None)


@crash_logger # Decorator to log any unhandled exceptions in main()
def main():
    """Main function to start the application."""
    print("Starting OverlayApp.")
    # Initial permission check (primarily for logging, actual request happens in delegate)
    permissions_granted = check_permissions(ask=False)
    if not permissions_granted:
        print("Accessibility permissions not yet granted. Global hotkey might require them. App will attempt to request if needed for event tap.")
        
    # --- Resolve ICON_PATH to an absolute path ---
    global ICON_PATH
    if not os.path.isabs(ICON_PATH):
        resolved_path = None
        # Try to find it relative to the package directory (if installed)
        try:
            import macos_llm_overlay
            package_dir = os.path.dirname(macos_llm_overlay.__file__)
            candidate = os.path.join(package_dir, ICON_PATH)
            if os.path.exists(candidate):
                resolved_path = candidate
        except ImportError:
            pass 

        # If not found, try relative to the script's directory (useful for development)
        if resolved_path is None:
            script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            bundle = NSBundle.mainBundle()
            if bundle:
                res_path = bundle.resourcePath()
                if res_path:
                    candidate_bundle_path = os.path.join(res_path, ICON_PATH)
                    if os.path.exists(candidate_bundle_path):
                        resolved_path = candidate_bundle_path

            if resolved_path is None: # Fallback if bundle method fails or not in bundle
                 resolved_path = os.path.join(script_dir, ICON_PATH) # For direct script execution
                 if not os.path.exists(resolved_path) and "../Resources" in script_dir: # A guess for script within a bundle structure
                    resolved_path = os.path.join(os.path.dirname(script_dir), "Resources", ICON_PATH)


        ICON_PATH = os.path.realpath(resolved_path) # Use canonical path
    print(f"Resolved ICON_PATH to: {ICON_PATH}")

    # --- Application Setup & Run ---
    app = NSApplication.sharedApplication()
    delegate = OverlayAppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run() # Start the main event loop

if __name__ == "__main__":
    main()
