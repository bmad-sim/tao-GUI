"""macOS: show "Tao GUI" in the menu bar and Dock instead of "python3.x".

macOS takes an application's menu-bar name from its main bundle's
``CFBundleName``. A Python script has no app bundle, so macOS shows the
interpreter's executable name. Setting ``CFBundleName`` in the main bundle's
info dictionary before the Cocoa application starts (that is, before the
``QApplication`` is created) changes the name.

This talks to the Objective-C runtime through ``ctypes``, so it needs no
extra package (such as PyObjC). Anything that goes wrong is ignored: the name
is cosmetic.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Optional


def _objc():
    lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    ctypes.cdll.LoadLibrary(ctypes.util.find_library("Foundation"))  # NSBundle, NSString
    lib.objc_getClass.restype = ctypes.c_void_p
    lib.objc_getClass.argtypes = [ctypes.c_char_p]
    lib.sel_registerName.restype = ctypes.c_void_p
    lib.sel_registerName.argtypes = [ctypes.c_char_p]
    return lib


def _send(lib, restype, obj, selector: bytes, *args):
    """objc_msgSend with an explicit prototype (required on Apple silicon)."""
    send = ctypes.cast(lib.objc_msgSend, ctypes.CFUNCTYPE(
        restype, ctypes.c_void_p, ctypes.c_void_p, *(type(a) for a in args)))
    return send(obj, lib.sel_registerName(selector), *args)


def _nsstring(lib, text: str) -> ctypes.c_void_p:
    cls = lib.objc_getClass(b"NSString")
    return ctypes.c_void_p(_send(lib, ctypes.c_void_p, cls, b"stringWithUTF8String:",
                                 ctypes.c_char_p(text.encode())))


def _info_dictionary(lib) -> Optional[int]:
    bundle = _send(lib, ctypes.c_void_p, lib.objc_getClass(b"NSBundle"), b"mainBundle")
    return _send(lib, ctypes.c_void_p, bundle, b"infoDictionary") if bundle else None


def set_app_name(name: str) -> bool:
    """Set the menu-bar name. Call before the QApplication is created.

    Returns True if the name was set (always False off macOS).
    """
    if sys.platform != "darwin":
        return False
    try:
        lib = _objc()
        info = _info_dictionary(lib)
        if not info:
            return False
        value = _nsstring(lib, name)
        for key in ("CFBundleName", "CFBundleDisplayName"):
            _send(lib, None, ctypes.c_void_p(info), b"setObject:forKey:",
                  value, _nsstring(lib, key))
        return app_name() == name
    except Exception:  # cosmetic only; never stop the GUI from starting
        return False


def app_name() -> Optional[str]:
    """The main bundle's CFBundleName (None off macOS or if unset)."""
    if sys.platform != "darwin":
        return None
    try:
        lib = _objc()
        info = _info_dictionary(lib)
        value = _send(lib, ctypes.c_void_p, ctypes.c_void_p(info), b"objectForKey:",
                      _nsstring(lib, "CFBundleName"))
        if not value:
            return None
        text = _send(lib, ctypes.c_char_p, ctypes.c_void_p(value), b"UTF8String")
        return text.decode() if text else None
    except Exception:
        return None
