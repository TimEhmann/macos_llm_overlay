from setuptools import setup
import os
import re
import subprocess
import sys

# Attempt to find the path to the _ctypes extension module.
# This is used on macOS to find dylibs like libffi that _ctypes depends on.
try:
    import _ctypes
    CTYPES_PATH = _ctypes.__file__
except (ImportError, AttributeError):
    CTYPES_PATH = None
    print("Warning: _ctypes module not found or its path is inaccessible.", file=sys.stderr)

def find_actual_path_for_dylib(dylib_reference_path, loader_path):
    """
    Resolves a dylib reference path (which can be relative like @rpath/ or @loader_path/)
    to an actual, absolute path on the filesystem.

    This function is crucial for bundling dependencies correctly on macOS,
    especially when dealing with libraries linked using @rpath or @loader_path.

    Args:
        dylib_reference_path (str): The reference path to the dylib (e.g., "@rpath/libffi.8.dylib").
        loader_path (str): The absolute path to the binary/library that loads the dylib.

    Returns:
        str or None: The resolved absolute real path to the dylib if found, otherwise None.
    """
    if not (dylib_reference_path and loader_path):
        return None

    loader_dir = os.path.dirname(loader_path)

    if dylib_reference_path.startswith('@rpath/'):
        # @rpath references are resolved by looking up LC_RPATH load commands
        # in the loader_path binary.
        try:
            # Use otool to list load commands.
            process = subprocess.run(['otool', '-l', loader_path], capture_output=True, text=True, check=True, encoding='utf-8')
            otool_output_lines = process.stdout.splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"Warning: 'otool -l {loader_path}' failed. This tool is needed to resolve @rpath.", file=sys.stderr)
            return None

        rpaths = []
        # Parse otool output for LC_RPATH commands.
        for i, line in enumerate(otool_output_lines):
            if "cmd LC_RPATH" in line:
                try:
                    path_line = otool_output_lines[i + 2].strip()
                    if path_line.startswith("path "):
                        rpath_val = path_line.split(" ", 1)[1].split(" (offset")[0]
                        # Substitute @loader_path within an rpath value.
                        rpath_val = rpath_val.replace('@loader_path', loader_dir)
                        rpaths.append(os.path.normpath(rpath_val))
                except IndexError:
                    # Malformed LC_RPATH entry, skip.
                    continue
        
        dylib_name_part = dylib_reference_path.replace('@rpath/', '')
        # Check each resolved rpath prefix.
        for rpath_prefix in rpaths:
            candidate_path = os.path.join(rpath_prefix, dylib_name_part)
            if os.path.exists(candidate_path):
                return os.path.realpath(candidate_path) # Return the canonical path.
        print(f"Warning: Could not resolve @rpath reference '{dylib_reference_path}' for loader '{loader_path}'. Rpaths searched: {rpaths}", file=sys.stderr)
        return None

    elif dylib_reference_path.startswith('@loader_path/'):
        # @loader_path is relative to the directory of the loading binary.
        path_part = dylib_reference_path.replace('@loader_path/', '')
        candidate_path = os.path.join(loader_dir, path_part)
        candidate_path = os.path.normpath(candidate_path)
        if os.path.exists(candidate_path):
            return os.path.realpath(candidate_path)
        print(f"Warning: Could not resolve @loader_path reference '{dylib_reference_path}' for loader '{loader_path}'.", file=sys.stderr)
        return None

    elif os.path.isabs(dylib_reference_path):
        # If it's an absolute path, just check if it exists.
        if os.path.exists(dylib_reference_path):
            return os.path.realpath(dylib_reference_path)
        else:
            print(f"Warning: Absolute path '{dylib_reference_path}' for dylib does not exist.", file=sys.stderr)
            return None
    else:
        # Other types of references (e.g., framework paths not starting with @) are not handled here.
        print(f"Warning: Unhandled dylib reference type: '{dylib_reference_path}'", file=sys.stderr)
        return None


def get_libffi_path(lib_name="libffi.8.dylib"):
    """
    Attempts to find the absolute path to a specific libffi dylib
    that the Python _ctypes module is linked against.

    This is important for py2app to bundle the correct version of libffi
    that the current Python interpreter uses, preventing crashes related to
    ABI incompatibilities if the system libffi is different.

    Args:
        lib_name (str): The specific name of the libffi dylib (e.g., "libffi.8.dylib").

    Returns:
        str or None: The resolved absolute real path to the libffi dylib if found, otherwise None.
    """
    if not CTYPES_PATH: # _ctypes module path couldn't be determined.
        return None

    try:
        # Use otool -L to list dynamic library dependencies of _ctypes.so.
        process = subprocess.run(['otool', '-L', CTYPES_PATH], capture_output=True, text=True, check=True, encoding='utf-8')
        otool_lines = process.stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"Warning: 'otool -L {CTYPES_PATH}' failed. Cannot determine {lib_name} path. 'otool' might be missing (Xcode Command Line Tools).", file=sys.stderr)
        return None

    # Regex to find the libffi line in otool output.
    lib_pattern = re.compile(r"^\s*([@\w/\.\-]+?" + re.escape(lib_name) + r")\s*\(compatibility version")

    for line in otool_lines:
        match = lib_pattern.match(line)
        if match:
            lib_reference_path = match.group(1)
            # Resolve the found reference (which might be @rpath/ or @loader_path/).
            actual_path = find_actual_path_for_dylib(lib_reference_path, CTYPES_PATH)
            if actual_path:
                print(f"Found {lib_name} at: {actual_path}", file=sys.stderr)
                return actual_path
            else:
                print(f"Warning: Could not resolve {lib_name} reference '{lib_reference_path}' from _ctypes.so.", file=sys.stderr)
                
    print(f"Warning: {lib_name} dependency not found for {CTYPES_PATH} via otool.", file=sys.stderr)
    
    # Fallback for Conda environments where libffi might be in sys.prefix/lib.
    conda_fallback_path = os.path.join(sys.prefix, "lib", lib_name)
    if os.path.exists(conda_fallback_path):
        print(f"Info: Using Conda fallback path for {lib_name}: {conda_fallback_path}", file=sys.stderr)
        return os.path.realpath(conda_fallback_path)
        
    return None

NAME = "macos_llm_overlay"

# --- py2app Configuration ---

# Main application script.
APP = [{
    'script': f'{NAME}/app.py',
}]

# Frameworks to explicitly include in the app bundle.
# This is particularly important for dylibs like libffi.
frameworks_to_include = []
libffi_path_resolved = get_libffi_path("libffi.8.dylib") # Attempt to find libffi.8.dylib
if libffi_path_resolved:
    frameworks_to_include.append(libffi_path_resolved)
else:
    # If specific libffi not found, try a more generic name as a last resort, or warn.
    libffi_path_resolved_generic = get_libffi_path("libffi.dylib")
    if libffi_path_resolved_generic:
        frameworks_to_include.append(libffi_path_resolved_generic)
        print(f"Warning: libffi.8.dylib not found, but found generic libffi.dylib at {libffi_path_resolved_generic}. Using this one.", file=sys.stderr)
    else:
        print(f"CRITICAL WARNING: libffi.8.dylib (and generic libffi.dylib) could not be found. "
              f"The application will likely fail to run due to missing libffi. "
              f"Please ensure 'otool' is available (Xcode Command Line Tools) "
              f"and your Python environment's _ctypes module is correctly linked to libffi.", file=sys.stderr)

# py2app options for building the .app bundle.
OPTIONS = {
    'resources': [f'{NAME}/macos_llm_overlay-icon.png'], # Non-code resources to include.
    'iconfile': f'{NAME}/macos_llm_overlay.icns',   # Application icon.
    'frameworks': frameworks_to_include,      # Dylibs/frameworks to bundle.
    'includes': [                             # Python modules to explicitly include.
        'pyobjc',
        'WebKit',
        'Quartz',
        'imp',
        'ctypes',
        'jaraco.text',
    ],
    'packages': [ # Python packages to include.
        NAME
    ],
    'plist': { # Contents for the app's Info.plist file.
        'CFBundleName': NAME,
        'CFBundleIdentifier': f'com.timehmann.macOSLLMOverlay',
        'LSUIElement': True,  # Makes the app an agent app (no Dock icon, no menu bar unless explicitly created).
    },
    'argv_emulation': False, # Do not emulate command-line arguments.
}

# --- Setup Function ---
setup(
    packages=[NAME], # Discover packages in the NAME directory.
    app=APP, # For py2app: specifies the main application script.
    options={'py2app': OPTIONS}, # For py2app: provides build options.
    setup_requires=['py2app'], # Ensures py2app is available for the setup process.
)
