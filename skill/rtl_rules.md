# Beginner RTL rules

- Prefer plain Verilog-2001 syntax unless SystemVerilog is explicitly requested.
- Use `always @(posedge clk)` for synchronous state updates.
- Use nonblocking assignment (`<=`) in sequential logic.
- Give registers an explicit reset value when the task specifies reset.
- Keep arithmetic widths explicit and preserve the requested output width.
- Give every combinational output a value on every path.
- Do not put `#delay`, `$display`, `$finish`, file I/O, or a testbench inside the DUT.
- Keep the external interface unchanged during repair.

