#!/usr/bin/env python3
"""Send a raw ESC/POS job straight to the USB receipt printer.

CUPS' usb backend reports Send-Document successful-ok for this printer
and then quietly drops the job on the floor, so we skip CUPS and talk to
the bulk endpoint ourselves. The udev node is root:lp mode 660 and the
folk user is in group lp, so this needs no privileges.

Usage: escpos-usb.py job.escpos [vid:pid]
       escpos-usb.py --probe [vid:pid]

--probe opens and claims the interface, then releases it, without
sending a byte. That is enough to prove the printer is connected and
talkable-to, and it does not waste a receipt -- which matters for the
nightly health check.
"""
import ctypes
import ctypes.util
import sys

VID, PID = 0x0FE6, 0x811E
EP_OUT = 0x01
CHUNK = 4096
TIMEOUT_MS = 10000


class Ctx(ctypes.Structure):
    pass


def load():
    name = ctypes.util.find_library("usb-1.0")
    if not name:
        raise SystemExit("libusb-1.0 not found")
    lib = ctypes.CDLL(name)
    lib.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p
    lib.libusb_open_device_with_vid_pid.argtypes = [
        ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
    lib.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_close.argtypes = [ctypes.c_void_p]
    lib.libusb_kernel_driver_active.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_detach_kernel_driver.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.libusb_bulk_transfer.argtypes = [
        ctypes.c_void_p, ctypes.c_ubyte, ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_uint]
    return lib


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    probe = sys.argv[1] == "--probe"
    data = b"" if probe else open(sys.argv[1], "rb").read()
    vid, pid = VID, PID
    if len(sys.argv) > 2:
        v, p = sys.argv[2].split(":")
        vid, pid = int(v, 16), int(p, 16)

    lib = load()
    ctx = ctypes.c_void_p()
    if lib.libusb_init(ctypes.byref(ctx)) != 0:
        raise SystemExit("libusb_init failed")

    handle = lib.libusb_open_device_with_vid_pid(ctx, vid, pid)
    if not handle:
        raise SystemExit(
            "could not open %04x:%04x -- is it plugged in, and are you in "
            "group lp?" % (vid, pid))

    if lib.libusb_kernel_driver_active(handle, 0) == 1:
        lib.libusb_detach_kernel_driver(handle, 0)

    rc = lib.libusb_claim_interface(handle, 0)
    if rc != 0:
        raise SystemExit("claim_interface failed: %d "
                         "(another process may hold it)" % rc)

    if probe:
        lib.libusb_release_interface(handle, 0)
        lib.libusb_close(handle)
        lib.libusb_exit(ctx)
        sys.stderr.write("probe ok: claimed %04x:%04x\n" % (vid, pid))
        return

    sent = 0
    try:
        for off in range(0, len(data), CHUNK):
            chunk = data[off:off + CHUNK]
            buf = (ctypes.c_ubyte * len(chunk)).from_buffer_copy(chunk)
            n = ctypes.c_int(0)
            rc = lib.libusb_bulk_transfer(
                handle, EP_OUT, buf, len(chunk), ctypes.byref(n), TIMEOUT_MS)
            if rc != 0:
                raise SystemExit(
                    "bulk_transfer failed at byte %d: rc=%d" % (off, rc))
            sent += n.value
    finally:
        lib.libusb_release_interface(handle, 0)
        lib.libusb_close(handle)
        lib.libusb_exit(ctx)

    sys.stderr.write("sent %d of %d bytes to %04x:%04x\n"
                     % (sent, len(data), vid, pid))


if __name__ == "__main__":
    main()
