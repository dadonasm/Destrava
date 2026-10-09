# -*- coding: utf-8 -*-
"""Destrava! - ler um arquivo do DISCO, e não da memória, para conferir cópias de verdade.

Logo depois de gravar, o sistema entrega a cópia que ainda está na memória (cache): um HD com defeito ou um
pendrive falsificado passariam na conferência. Aqui:
  Windows  CreateFileW com FILE_FLAG_NO_BUFFERING (lê do disco, sempre)
  Linux    posix_fadvise(DONTNEED) antes de ler (descarta o cache das páginas já gravadas)
  Mac      F_NOCACHE (melhor esforço: o macOS pode ainda usar a memória)
"""
import hashlib
import os
import sys

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
BLOCO = 4 * 1024 * 1024  # múltiplo do tamanho de setor (exigência do NO_BUFFERING)
METODO = "lido do disco" if (IS_WIN or hasattr(os, "posix_fadvise")) else "melhor esforço: o macOS pode usar a memória"


def _win(path):
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.VirtualAlloc.restype = ctypes.c_void_p
    k.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
    k.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
    k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    p = os.path.abspath(path)
    if not p.startswith("\\\\?\\"):
        p = "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p
    # leitura, compartilhado para leitura/escrita, arquivo existente, sem cache + leitura sequencial
    h = k.CreateFileW(p, 0x80000000, 0x1 | 0x2, None, 3, 0x20000000 | 0x08000000, None)
    if not h or h == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    buf = k.VirtualAlloc(None, BLOCO, 0x3000, 0x04)  # memória alinhada à página
    if not buf:
        k.CloseHandle(h)
        raise MemoryError("sem memória para ler do disco")
    try:
        lidos = wintypes.DWORD(0)
        while True:
            if not k.ReadFile(h, buf, BLOCO, ctypes.byref(lidos), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if lidos.value == 0:
                break
            yield ctypes.string_at(buf, lidos.value)
            if lidos.value < BLOCO:
                break
    finally:
        k.VirtualFree(buf, 0, 0x8000)
        k.CloseHandle(h)


def blocos(path):
    """Os bytes do arquivo, lidos do disco (veja METODO)."""
    if IS_WIN:
        g = _win(path)
        try:
            primeiro = next(g, None)
        except OSError:
            g = None  # disco de rede ou sistema que recusa leitura sem cache: lê do jeito normal
        if g is not None:
            if primeiro is not None:
                yield primeiro
                for b in g:
                    yield b
            return
    with open(path, "rb") as f:
        fd = f.fileno()
        if hasattr(os, "posix_fadvise"):
            try:
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            except OSError:
                pass
        elif IS_MAC:
            try:
                import fcntl
                fcntl.fcntl(fd, getattr(fcntl, "F_NOCACHE", 48), 1)
            except Exception:
                pass
        while True:
            b = f.read(BLOCO)
            if not b:
                break
            yield b


def sha256(path):
    h = hashlib.sha256()
    for b in blocos(path):
        h.update(b)
    return h.hexdigest()
