import sys
import traceback
import functools
import datetime
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
from macos_llm_overlay.config import LOG_DIR

def check_permissions(ask=False):
    """
    Checks for macOS accessibility permissions required for global hotkeys.

    Args:
        ask (bool): If True, the system will prompt the user to grant permissions
                    if they haven't been granted already. If False, it will
                    only check the current status without prompting.

    Returns:
        bool: True if the process has accessibility permissions, False otherwise.
    """
    options = {kAXTrustedCheckOptionPrompt: ask}
    is_trusted = AXIsProcessTrustedWithOptions(options)
    return is_trusted

def crash_logger(func):
    """
    A decorator that wraps a function to catch, log, and re-raise any exceptions.

    Exceptions are logged to stderr and to a timestamped file in the application's
    log directory (defined by LOG_DIR in config.py).

    Args:
        func (callable): The function to be wrapped.

    Returns:
        callable: The wrapped function.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            
            # Generate a unique log file name
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S.%f")
            log_file_name = f"crash_{func.__name__}_{timestamp}.log"
            log_file_path = LOG_DIR / log_file_name

            # Get current exception details
            exc_type, exc_value, exc_traceback = sys.exc_info()
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            tb_str = "".join(tb_lines)

            # Prepare the error message
            error_message_header = f"--- UNHANDLED EXCEPTION IN {func.__name__} ---"
            current_time_iso = datetime.datetime.now().isoformat()
            
            full_error_message = (
                f"{error_message_header}\n"
                f"Timestamp: {current_time_iso}\n"
                f"Function: {func.__name__}\n"
                f"Args: {args}\n"
                f"Kwargs: {kwargs}\n"
                f"Exception Type: {exc_type.__name__ if exc_type else 'N/A'}\n"
                f"Exception Value: {exc_value}\n"
                f"--- Traceback ---\n{tb_str}"
            )
            
            # Print to stderr
            print(f"CRITICAL ERROR: {error_message_header}. See details below and in log file.", file=sys.stderr)
            sys.stderr.write(full_error_message + "\n")
            sys.stderr.flush()
            
            # Write to log file
            try:
                with open(log_file_path, "w", encoding='utf-8') as f:
                    f.write(full_error_message)
                print(f"Crash report saved to: {log_file_path}", file=sys.stderr)
            except IOError as ioe:
                print(f"CRITICAL ERROR: Could not write crash log to {log_file_path}: {ioe}", file=sys.stderr)
            
            # Re-raise the exception
            raise
    return wrapper
