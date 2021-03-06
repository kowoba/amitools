from amitools.vamos.Log import log_mem, log_mem_int, log_instr


class TraceManager(object):
  trace_val_str = ("%02x      ", "%04x    ", "%08x")

  def __init__(self, cpu, label_mgr):
    self.cpu = cpu
    self.label_mgr = label_mgr

  # trace callback from CPU core
  def trace_mem(self, mode, width, addr, value=0):
    self._trace_mem(log_mem, mode, width, addr, value)
    return 0

  def trace_int_mem(self, mode, width, addr, value=0,
                    text="", addon=""):
    self._trace_mem(log_mem_int, mode, width, addr, value, text, addon)

  def trace_int_block(self, mode, addr, size,
                      text="", addon=""):
    info, label = self._get_mem_info(addr)
    log_mem_int.info(
        "%s(B): %06x: +%06x   %6s  [%s] %s",
        mode, addr, size,
        text, info, addon)

  def trace_code_line(self, pc):
    label, sym, src = self._get_disasm_info(pc)
    _, txt = self.cpu.disassemble(pc)
    if sym is not None:
      log_instr.info("%s%s:", " "*40, sym)
    if src is not None:
      log_instr.info("%s%s", " "*50, src)
    log_instr.info("%-40s  %06x    %-20s" % (label, pc, txt))

  # ----- internal -----

  def _get_disasm_info(self, addr):
    if not self.label_mgr:
      return "N/A", None, None
    label = self.label_mgr.get_label(addr)
    sym = None
    src = None
    if label != None:
      mem = "@%06x +%06x %s" % (label.addr, addr - label.addr, label.name)
      if hasattr(label, 'segment'):
        sym, src = self._get_segment_info(label.segment, label.addr, addr)
    else:
      mem = "N/A"
    return mem, sym, src

  def _get_segment_info(self, segment, segment_addr, addr):
    rel_addr = addr - segment_addr
    sym = segment.find_symbol(rel_addr)
    info = segment.find_debug_line(rel_addr)
    if info is None:
      src = None
    else:
      f = info.get_file()
      src_file = f.get_src_file()
      src_line = info.get_src_line()
      src = "[%s:%d]" % (src_file, src_line)
    return sym, src

  def _trace_mem(self, log, mode, width, addr, value,
                 text="", addon=""):
    val = self.trace_val_str[width] % value
    info, label = self._get_mem_info(addr)
    if text == "" and addon == "" and label is not None:
      text, addon = self._get_extra(label, mode, addr, width, value)
    log.info("%s(%d): %06x: %s  %6s  [%s] %s",
             mode, 2**width, addr, val,
             text, info, addon)

  def _get_mem_info(self, addr, width=None):
    if not self.label_mgr:
      return "??", None
    label = self.label_mgr.get_label(addr)
    if label is not None:
      txt = "@%06x +%06x %s" % (label.addr, addr - label.addr, label.name)
      return txt, label
    else:
      return "??", None

  def _get_extra(self, label, mode, addr, width, value):
    if hasattr(label, 'lib'):
      text, addon = self._get_lib_extra(label, mode, addr, width, value)
      if text != "":
        return text, addon
    if hasattr(label, 'struct'):
      return self._get_struct_extra(label, addr, width)
    else:
      return "", ""

  def _get_struct_extra(self, label, addr, width):
    delta = addr - label.struct_begin
    if delta >= 0 and delta < label.struct_size:
      struct = label.struct(None, addr)
      st, field, f_delta = struct.get_struct_field_for_offset(delta)

      type_name = struct.get_type_name()
      name = st.get_field_path_name(field)
      type_sig = field.type_sig
      addon = "%s+%d = %s(%s)+%d" % (type_name, delta,
                                     name, type_sig, f_delta)
      return "Struct", addon
    else:
      return "", ""

  op_jmp = 0x4ef9
  op_reset = 0x04e70

  def _get_fd_str(self, lib, bias):
    if lib.fd is not None:
      f = lib.fd.get_func_by_bias(bias)
      if f is not None:
        return f.get_str()
    return ""

  def _get_lib_extra(self, label, mode, addr, width, value):
    # inside jump table
    if addr < label.lib_base:
      # read word
      if mode == 'R' and width == 1:
        # is it trapped?
        if value & 0xa000 == 0xa000:
          delta = label.lib_base - addr
          off = delta / 6
          addon = "-%d [%d]  " % (delta, off)
          addon += self._get_fd_str(label.lib, delta)
          return "TRAP", addon
        # native lib jump
        elif value == self.op_jmp:
          delta = label.lib_base - addr
          addon = "-%d  " % delta
          addon += self._get_fd_str(label.lib, delta)
          return "JUMP", addon
        # reset
        elif value == self.op_reset:
          return "RESET", ""
        # something inside jump table
        else:
          return "JUMP?", ""
      else:
        return "JUMP?", ""
    else:
      return "", ""
