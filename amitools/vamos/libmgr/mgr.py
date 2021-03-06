import datetime
import logging
from amitools.vamos.Log import log_libmgr
from amitools.vamos.atypes import Library
from amitools.vamos.libcore import VLibManager
from amitools.vamos.libnative import ALibManager, LibLoader


class LibManager(object):
  """the library manager handles both native and vamos libs"""

  MODE_OFF = 'off'
  MODE_AUTO = 'auto'
  MODE_VAMOS = 'vamos'
  MODE_AMIGA = 'amiga'
  MODE_FAKE = 'fake'

  def __init__(self, machine, alloc, segloader,
               cfg=None, profiler_cfg=None):
    self.mem = machine.get_mem()
    self.cfg = cfg
    self.vlib_mgr = VLibManager(machine, alloc,
                                profiler_cfg=profiler_cfg)
    self.alib_mgr = ALibManager(machine, alloc, segloader)

  def add_ctx(self, name, ctx):
    """allow to add vlib contexts"""
    ctx.lib_mgr = self
    self.vlib_mgr.add_ctx(name, ctx)

  def get_vlib_by_addr(self, addr):
    """return associated vlib for a base lib address"""
    return self.vlib_mgr.get_vlib_by_addr(addr)

  def get_vlib_by_name(self, name):
    """return associated vlib for a name"""
    return self.vlib_mgr.get_vlib_by_name(name)

  def bootstrap_exec(self, exec_info=None):
    """setup exec vlib as first and essential lib"""
    lib_cfg = None
    if self.cfg:
      lib_cfg = self.cfg.get_lib_config("exec.library")
    return self.vlib_mgr.bootstrap_exec(exec_info)

  def shutdown(self, run_sp=None):
    """cleanup libs

    try to expunge all libs and report still open ones
    """
    log_libmgr.info("+shutdown")
    aleft = self.alib_mgr.shutdown(run_sp)
    if aleft > 0:
      log_libmgr.warn("shutdown: can't expunge %d amiga libs/devs!", aleft)
    vleft = self.vlib_mgr.shutdown()
    if vleft > 0:
      log_libmgr.warn("shutdown: can't expunge %d vamos libs/devs!", vleft)
    left = vleft + aleft
    log_libmgr.info("-shutdwon: aleft=%d, vleft=%d", aleft, vleft)
    return left

  def expunge_libs(self, run_sp=None):
    """expunge all unused libs

       return number of libs _not_ expunged
    """
    log_libmgr.info("+expunge_libs")
    aleft = self.alib_mgr.expunge_libs(run_sp)
    vleft = self.vlib_mgr.expunge_libs()
    log_libmgr.info("-expunge_libs: aleft=%d, vleft=%d", aleft, vleft)
    return vleft + aleft

  def expunge_devs(self, run_sp=None):
    """expunge all unused devs

       return number of libs _not_ expunged
    """
    log_libmgr.info("+expunge_devs")
    aleft = 0  # TBD
    vleft = self.vlib_mgr.expunge_devs()
    log_libmgr.info("-expunge_devs: aleft=%d, vleft=%d", aleft, vleft)
    return vleft

  def expunge_lib(self, addr, run_sp=None):
    """expunge a library given by base address

       return True if lib was expunged
    """
    log_libmgr.info("expunge_lib: @%06x", addr)
    vlib = self.vlib_mgr.get_vlib_by_addr(addr)
    if vlib:
      return self.vlib_mgr.expunge_lib(vlib)
    elif self.alib_mgr.is_load_addr(addr):
      seglist = self.alib_mgr.expunge_lib(addr, run_sp)
      return seglist != 0
    else:
      log_libmgr.error("expunge: unknown lib @%06x!", addr)

  def close_lib(self, addr, run_sp=None):
    """close a library

       return True if lib was expunged, too
    """
    log_libmgr.info("close_lib: @%06x", addr)
    vlib = self.vlib_mgr.get_vlib_by_addr(addr)
    if vlib:
      return self.vlib_mgr.close_lib(vlib)
    elif self.alib_mgr.is_base_addr(addr):
      seglist = self.alib_mgr.close_lib(addr, run_sp)
      return seglist != 0
    else:
      log_libmgr.error("close: unknown lib @%06x!", addr)

  def open_lib(self, full_name, open_ver=0, lock=None, run_sp=None,
               mode=None, version=None):
    """open a library

       return lib_base addr or 0
    """
    # get base name
    base_name = LibLoader.get_lib_base_name(full_name)
    log_libmgr.info("open_lib: '%s' ver=%d -> base_name='%s'",
                    full_name, open_ver, base_name)
    # get lib params
    mode, version = self._get_lib_params(
        full_name, base_name, mode, version)
    log_libmgr.info("params: mode=%s, version=%d",
                    mode, version)
    # handle mode
    if mode == self.MODE_OFF:
      return 0
    try_vlib, try_alib, fake = self._map_mode(mode)

    # try vamos first
    addr = 0
    vlib = None
    if try_vlib:
      vlib = self.vlib_mgr.open_lib_name(base_name,
                                         version=version,
                                         fake=fake)
      if vlib:
        addr = vlib.get_addr()
        log_libmgr.info("got vlib: @%06x", addr)
    # try amiga lib
    if try_alib and addr == 0:
      addr = self.alib_mgr.open_lib(full_name, lock, run_sp)
      if addr > 0:
        log_libmgr.info("got alib: @%06x", addr)

    # got a lib? check version
    if addr > 0:
      save_addr = addr
      if open_ver > 0:
        addr = self._check_version(full_name, addr, open_ver)
      # lib is too old: close again
      if addr == 0:
        if vlib:
          self.vlib_mgr.close_lib(vlib)
        else:
          self.alib_mgr.close_lib(save_addr, run_sp=run_sp)
    # result lib base
    return addr

  def _map_mode(self, mode):
    if mode == self.MODE_AUTO:
      try_vlib = True
      try_alib = True
      fake = False
    elif mode == self.MODE_VAMOS:
      try_vlib = True
      try_alib = False
      fake = False
    elif mode == self.MODE_AMIGA:
      try_vlib = False
      try_alib = True
      fake = False
    elif mode == self.MODE_FAKE:
      try_vlib = True
      try_alib = False
      fake = True
    else:
      raise ValueError("invalid lib mode: '%s'" % mode)
    return try_vlib, try_alib, fake

  def _check_version(self, name, addr, open_ver):
    # check version
    lib = Library(self.mem, addr)
    lib_ver = lib.version
    if lib_ver < open_ver:
      log_libmgr.warn("lib '%s' has too low version: %d < %d",
                      name, lib_ver, open_ver)
      return 0
    else:
      log_libmgr.info("lib '%s' version %d ok for open version %d",
                      name, lib_ver, open_ver)
      return addr

  def _get_lib_params(self, full_name, base_name,
                      force_mode, force_version):
    # get lib config
    if self.cfg:
      lib_cfg = self.cfg.get_lib_config(full_name, base_name)
      self._dump_lib_cfg(full_name, lib_cfg)
      mode = lib_cfg.mode
      version = lib_cfg.version
    else:
      lib_cfg = None
      mode = "auto"
      version = 0  # take lib version
    if force_mode:
      mode = force_mode
    if force_version:
      version = force_version
    return mode, version

  def _dump_lib_cfg(self, lib_name, lib_cfg):
    items = ["for_lib='%s'" % lib_name, "use_cfg='%s'" % lib_cfg.name]
    for key in lib_cfg._keys:
      items.append("%s=%s" % (key, getattr(lib_cfg, key)))
    log_libmgr.info(" ".join(items))
