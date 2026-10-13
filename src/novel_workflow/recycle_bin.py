"""Windows recycle-only deletion. No permanent-delete fallback or dialogs."""
import os
from pathlib import Path


def recycle_snapshot(path):
    if os.name != 'nt':
        raise OSError('Windows Recycle Bin is unavailable; history was preserved')
    import pythoncom
    import pywintypes
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink

    class RecycleOnlySink(FileOperationProgressSink):
        def PreDeleteItem(self, flags, item):
            if not flags & shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE:
                raise COMException(desc='Recycle Bin unavailable', scode=-2147467259)
            return 0

    pythoncom.CoInitialize()
    try:
        operation = pythoncom.CoCreateInstance(shell.CLSID_FileOperation, None,
                                               pythoncom.CLSCTX_ALL, shell.IID_IFileOperation)
        operation.SetOperationFlags(shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI
                                    | shellcon.FOF_SILENT | shellcon.FOFX_EARLYFAILURE
                                    | 0x20000000 | 0x00080000)
        sink = RecycleOnlySink()
        wrapped = pythoncom.WrapObject(sink, shell.IID_IFileOperationProgressSink)
        item = shell.SHCreateItemFromParsingName(str(path), None, shell.IID_IShellItem)
        operation.DeleteItem(item, wrapped)
        result = operation.PerformOperations()
        if result or operation.GetAnyOperationsAborted() or not sink.newItem:
            raise OSError('Snapshot could not be moved to Windows Recycle Bin')
        destination = Path(sink.newItem)
        if Path(path).exists() or not destination.is_dir():
            raise OSError('Recycle Bin destination could not be verified')
        return destination
    except pywintypes.com_error as exc:
        raise OSError('Recycle Bin operation failed: ' + str(exc)) from exc
    finally:
        pythoncom.CoUninitialize()
