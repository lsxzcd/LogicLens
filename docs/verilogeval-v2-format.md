# VerilogEval v2 — `dataset_spec-to-rtl` on-disk format & harness mechanics

All facts below were read from actual file contents fetched over HTTP (URLs listed per section).
Everything is marked **[VERIFIED]** (read from a fetched file) or **[INFERRED]** / **[NOT VERIFIED]**.

Repo: https://github.com/NVlabs/verilog-eval  (default branch `main`, = "VerilogEval V2")
Fetched at: commit `c498220d0a52248f8e3fdffe279075215bde2da6` (tree sha for `main`), problem data blobs as listed.

---

## 0. TL;DR for the adapter author

**There is no JSONL and no `canonical_solution` / `declaration` / `task_id` field in `dataset_spec-to-rtl`.**
The v2 dataset is a directory of **plain-text / SystemVerilog files**, 4 entries per problem:

| v1 JSONL concept (branch `release/1.0.0`) | v2 `dataset_spec-to-rtl/` equivalent |
|---|---|
| `task_id` (e.g. `"zero"`) | file stem `Prob001_zero` (in `problems.txt` and as filename prefix) |
| `prompt` (module header text) | `ProbNNN_<name>_prompt.txt` — natural-language spec |
| (`declaration`) — **does not exist even in v1** | n/a; interface is prose bullets inside `_prompt.txt` |
| `canonical_solution` (module body) | `ProbNNN_<name>_ref.sv` — `module RefModule (...)` |
| `test` (whole TB + reference) | `ProbNNN_<name>_test.sv` — `module stimulus_gen` + `module tb`; **reference split out into `_ref.sv`** |

DUT module name must be exactly **`TopModule`**. Reference module is **`RefModule`**. Pass ⇔ the TB's
`final` block prints `Mismatches: 0 in <N> samples`.

---

## 1. Repository layout

**[VERIFIED]** `https://api.github.com/repos/NVlabs/verilog-eval/contents/`
and `https://api.github.com/repos/NVlabs/verilog-eval/git/trees/main?recursive=1`

Top level of `main`:

```
.gitignore
LICENSE
Makefile.in
README.md
configure            (generated autoconf script, 93072 B, mode 100755)
configure.ac
count_failures.py
pass_rate_to_csv.py
dataset_code-complete-iccad2023/
dataset_spec-to-rtl/
scripts/
```

### `dataset_spec-to-rtl/` **[VERIFIED]**
`https://api.github.com/repos/NVlabs/verilog-eval/contents/dataset_spec-to-rtl`
Contains exactly one `problems.txt` plus **three** files per problem:

```
problems.txt
Prob001_zero_prompt.txt
Prob001_zero_ref.sv
Prob001_zero_test.sv
Prob002_m2014_q4i_prompt.txt
Prob002_m2014_q4i_ref.sv
Prob002_m2014_q4i_test.sv
...
```

* **No `.jsonl`, no `.json`, no `_ifc.txt`** in this directory.
  Confirmed by 404 on probes: `dataset_spec-to-rtl/Prob001_zero_ifc.txt` and
  `dataset_spec-to-rtl/Prob032_vector0_ifc.txt` → HTTP 404.
  **[INFERRED]** therefore 156 × 3 + 1 = **469 files**.

### `dataset_code-complete-iccad2023/` **[VERIFIED]**
`https://api.github.com/repos/NVlabs/verilog-eval/contents/dataset_code-complete-iccad2023`
Same three files **plus a fourth `_ifc.txt`** (the raw Verilog module header):

```
Prob001_zero_ifc.txt      (37 B)
Prob001_zero_prompt.txt   (82 B)
Prob001_zero_ref.sv       (72 B)   <- byte-identical to the spec-to-rtl one (same blob sha 89ae9a83...)
Prob001_zero_test.sv      (2670 B) <- byte-identical to the spec-to-rtl one (same blob sha fd4c826e...)
```

Note the **ref/test files are identical blobs across the two splits** (same git blob SHAs); only the
prompt differs (plus `_ifc.txt` existing only in code-complete). This matches the README: *"Problem
themselves are identical between the two datasets and only the task format changes."*

### `scripts/` **[VERIFIED]**
```
scripts/echo-progress
scripts/prompt-example-prefix.txt                    (legacy "### Problem/Solution" style, 3131 B)
scripts/sv-generate                                  (LLM front-end, 19898 B)
scripts/sv-iv-analyze                                (result analyzer / pass-fail classifier, 10861 B)
scripts/verilog-example-prefix_code-complete-iccad2023_{1,2,3,4}-shot.txt
scripts/verilog-example-prefix_spec-to-rtl_{1,2,3,4}-shot.txt
scripts/verilog-example-prefix_spec-to-rtl_1-shot default.txt
```

### Where the JSONL lives
**[VERIFIED]** The `.jsonl` files exist **only on the legacy branch `release/1.0.0` (VerilogEval v1)**:
`https://api.github.com/repos/NVlabs/verilog-eval/contents/data?ref=release/1.0.0`
```
data/VerilogEval_Human.jsonl     (726829 B)
data/VerilogEval_Machine.jsonl   (619265 B)
data/example/
data/human-eval/
```
Plus `verilog_eval/{data,execution,evaluation,evaluate_functional_correctness}.py`.
The v2 README states: *"MachineEval is not supported in VerilogEvalV2, only the Human Eval problem
statements."* and *"The new scripts manage the dataset as plain text files (instead of a large JSONL file)."*

---

## 2. Problem record format

### 2a. v2 `dataset_spec-to-rtl` — **there is no JSON record.**
The "record" is the triple `(_prompt.txt, _ref.sv, _test.sv)` keyed by the stem from `problems.txt`.
Quoted verbatim below (see §3 for the full prompt).

### 2b. v1 JSONL field names **[VERIFIED, for comparison]**
`https://raw.githubusercontent.com/NVlabs/verilog-eval/release/1.0.0/data/VerilogEval_Human.jsonl`
(one JSON object per line). **Exact field names: `task_id`, `prompt`, `canonical_solution`, `test`.**
There is **no `declaration` field** and no `name`/`id`/`level` field. First record verbatim
(long `test` string shortened with `…`; all field NAMES exact):

```json
{"task_id": "gatesv",
 "prompt": "module top_module (\n\tinput [3:0] in,\n\toutput [2:0] out_both,\n\toutput [3:1] out_any,\n\toutput [3:0] out_different\n);\n",
 "canonical_solution": "\n\tassign out_both = in[2:0] & in[3:1];\n\tassign out_any = in[2:0] | in[3:1];\n\tassign out_different = in^{in[0], in[3:1]};\n\t\nendmodule\n",
 "test": "`timescale 1 ps/1 ps\n`define OK 12\n`define INCORRECT 13\nmodule reference_module (\n\tinput [3:0] in,\n … [canonical_solution text is spliced in verbatim] … \nendmodule\n\n\nmodule stimulus_gen (\n\tinput clk,\n\tinput tb_match,\n\toutput logic [3:0] in,\n … \nendmodule\n\nmodule tb();\n … $display(\"Mismatches: %1d in %1d samples\", stats1.errors, stats1.clocks);\n … \nendmodule\n"}
```

In v1 the DUT module is **`top_module`** (lowercase) and the reference is inlined as
**`module reference_module`** inside the `test` string. In v2 both were renamed and split.

### 2c. v2 verbatim example — `Prob001_zero` **[VERIFIED]**

`dataset_spec-to-rtl/Prob001_zero_prompt.txt` (211 B, complete, verbatim — note the leading blank line):

```
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - output zero

The module should always outputs a LOW.
```

`dataset_spec-to-rtl/Prob001_zero_ref.sv` (72 B, complete, verbatim):

```verilog
module RefModule (
  output zero
);

  assign zero = 1'b0;

endmodule
```

`dataset_spec-to-rtl/Prob001_zero_test.sv` (2670 B). Structure verbatim (wavedrom helper bodies elided):

```verilog
`timescale 1 ps/1 ps
`define OK 12
`define INCORRECT 13

module stimulus_gen (
	input clk,
	output reg[511:0] wavedrom_title,
	output reg wavedrom_enable
);
	task wavedrom_start(input[511:0] title = ""); endtask
	task wavedrom_stop; #1; endtask
	initial begin
		wavedrom_start("Output should 0");
		repeat(20) @(posedge clk, negedge clk);
		wavedrom_stop();
		#1 $finish;
	end
endmodule

module tb();
	typedef struct packed {
		int errors;          int errortime;
		int errors_zero;     int errortime_zero;
		int clocks;
	} stats;
	stats stats1;

	wire[511:0] wavedrom_title;
	wire wavedrom_enable;
	int wavedrom_hide_after_time;

	reg clk=0;
	initial forever #5 clk = ~clk;

	logic zero_ref;
	logic zero_dut;

	initial begin
		$dumpfile("wave.vcd");
		$dumpvars(1, stim1.clk, tb_mismatch ,zero_ref,zero_dut );
	end

	wire tb_match;		// Verification
	wire tb_mismatch = ~tb_match;

	stimulus_gen stim1 ( .clk, .*  );
	RefModule   good1  ( .zero(zero_ref) );
	TopModule   top_module1 ( .zero(zero_dut) );

	bit strobe = 0;
	task wait_for_end_of_timestep;
		repeat(5) begin strobe <= !strobe; @(strobe); end
	endtask

	final begin
		if (stats1.errors_zero) $display("Hint: Output '%s' has %0d mismatches. First mismatch occurred at time %0d.", "zero", stats1.errors_zero, stats1.errortime_zero);
		else $display("Hint: Output '%s' has no mismatches.", "zero");
		$display("Hint: Total mismatched samples is %1d out of %1d samples\n", stats1.errors, stats1.clocks);
		$display("Simulation finished at %0d ps", $time);
		$display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
	end

	// Verification: XORs on the right makes any X in good_vector match anything, but X in dut_vector will only match X.
	assign tb_match = ( { zero_ref } === ( { zero_ref } ^ { zero_dut } ^ { zero_ref } ) );
	// Use explicit sensitivity list here. @(*) causes NetProc::nex_input() to be called when trying to compute
	// the sensitivity list of the @(strobe) process, which isn't implemented.
	always @(posedge clk, negedge clk) begin
		stats1.clocks++;
		if (!tb_match) begin
			if (stats1.errors == 0) stats1.errortime = $time;
			stats1.errors++;
		end
		if (zero_ref !== ( zero_ref ^ zero_dut ^ zero_ref ))
		begin if (stats1.errors_zero == 0) stats1.errortime_zero = $time;
			stats1.errors_zero = stats1.errors_zero+1'b1; end
	end

	// add timeout after 100K cycles
	initial begin
		#1000000
		$display("TIMEOUT");
		$finish();
	end
endmodule
```

---

## 3. How the prompt is delivered

**[VERIFIED]** The whole natural-language specification is in **one `_prompt.txt` file**.
It **does** state the interface, but **as prose bullets, not as Verilog**.

`Prob032_vector0_prompt.txt` verbatim (complete):

```
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  vec  (3 bits)
 - output outv (3 bits)
 - output o2
 - output o1
 - output o0

The module has one 3-bit input, then outputs the same vector, and also
splits it into three separate 1-bit outputs. Connect output o0 to the
input vector's position 0, o1 to position 1, etc.
```

Conventions observed in every prompt sampled:
* Fixed opening boilerplate: *"I would like you to implement a module named **TopModule** with the following interface. All input and output ports are one bit unless otherwise specified."*
* Ports as `- input  <name>` / `- output <name>`, with width annotation `(N bits)` **only when ≠ 1 bit** (`- input  clk`, `- input  vec  (3 bits)`).
* Then free-form behavioural prose; sequential problems add *"Assume all sequential logic is triggered on the positive edge of the clock."* and describe reset polarity/synchronicity (e.g. `Prob137_fsm_serial_prompt.txt`).
* Some problems embed a **timing/waveform table** as plain text (e.g. `Prob090_circuit1_prompt.txt` has a `time a b q` table).
* **No `module ... (...)` Verilog declaration, no `logic`/`wire`, no ports-with-types.** The prompt alone is not compilable.
* **No instruction about output format** inside `_prompt.txt` (see below).

**[VERIFIED]** The port list is **not** supplied as a separate `declaration` field for `spec-to-rtl`.
That separate artifact (`_ifc.txt`) exists **only** in `dataset_code-complete-iccad2023`, and is the
compilable stub that the harness prepends when the model returns a bare body:

`dataset_code-complete-iccad2023/Prob001_zero_ifc.txt` verbatim:
```verilog
module TopModule (
  output zero
);
```

**So: for `spec-to-rtl` the task text alone specifies the interface — textually.** The model must
emit a full module, and it must be named `TopModule` with exactly the port names/widths listed.

### Prompt assembly (what the model actually receives) **[VERIFIED]**
`https://raw.githubusercontent.com/NVlabs/verilog-eval/main/scripts/sv-generate`

```python
prompts['spec-to-rtl'] = {
  'system_msg'    : "\nYou are a Verilog RTL designer that only writes code using correct Verilog syntax.\n",
  'prompt_prefix' : ""
}
...
full_prompt += "\nQuestion:\n"
full_prompt += prompt.strip() + "\n"
if opts.rules:                        # --rules ; configure.ac default is "no"
    full_prompt += prompt_rules_suffix
if not opts.explain:                  # --explain not passed by default
    full_prompt = full_prompt.rstrip() + "\n" + prompt_no_explain_suffix
full_prompt += "\nAnswer:\n"

msgs = [ SystemMessage(system_msg), HumanMessage(full_prompt) ]
```

with

```python
prompt_no_explain_suffix = """
Enclose your code with [BEGIN] and [DONE]. Only output the code snippet
and do NOT output anything else.
"""
```

Response extraction (same script): primary path collects lines between `[BEGIN]` and `[DONE]`
(also accepting `[BEGIN]`/`[DONE]` at line start/end); **fallback** path is markdown-fence
extraction with the comment marker
`// VERILOG-EVAL: response did not use <CODE></CODE> correctly` appended.
No `_ifc.txt` prefix is ever prepended for `spec-to-rtl` (the model must emit `module TopModule`).

In-context-learning examples are separate files selected by shot count, e.g.
`scripts/verilog-example-prefix_spec-to-rtl_1-shot.txt` verbatim (this IS the official ICL format):

```
Question:
Implement a hardware module named TopModule with the following interface.
All input and output ports are one bit unless otherwise specified.

 - input  in_ (8 bits)
 - output out (8 bits)

The module should implement an incrementer which increments the input by
one and writes the result to the output. Assume all values are encoded as
two's complement binary numbers.

Enclose your code with [BEGIN] and [DONE]. Only output the code snippet
and do NOT output anything else.

Answer:
[BEGIN]
module TopModule
(
  input  logic [7:0] in_,
  output logic [7:0] out
);

  // Combinational logic

  assign out = in_ + 1;

endmodule
[DONE]
```

---

## 4. Testbench handling

**[VERIFIED]** Testbenches are **separate files**, one per problem: `dataset_spec-to-rtl/<stem>_test.sv`.
They are **not** embedded in any JSON. The reference DUT is also a separate file: `<stem>_ref.sv`.

Module naming convention inside `_test.sv` **[VERIFIED across Prob001, Prob050, Prob060, Prob143, Prob156]**:

| role | module name | instantiated as |
|---|---|---|
| top / testbench | `tb` | selected via `iverilog -s tb` |
| stimulus | `stimulus_gen` | `stimulus_gen stim1 ( ... )` |
| reference DUT (from `_ref.sv`) | `RefModule` | `RefModule good1 ( ... )` |
| DUT under test (model output) | **`TopModule`** | `TopModule top_module1 ( ... )` |

Port wiring: outputs of the DUTs are connected by **explicit named ports** to `*_ref` / `*_dut` locals
(`.zero(zero_ref)`, `.zero(zero_dut)`, `.next_state(next_state_ref)`, `.next_state(next_state_dut)`).
Inputs are usually given as bare named shorthand (`.in`, `.state`). `stimulus_gen` is connected with
`.clk, .* , <explicit names>` so its ports bind to same-named `tb` locals.
**Consequence: port ORDER is irrelevant, but port NAMES and WIDTHS must match exactly.**

### Pass/fail determination
**[VERIFIED]** The testbench prints, from its `final` block:

```verilog
$display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
```

`stats1.errors` is incremented every half-clock-edge where the ref vector and DUT vector disagree.
**PASS ⇔ that number is 0.** There is **no** `OK`/`INCORRECT` print in v2 (the `` `define OK 12 `` /
`` `define INCORRECT 13 `` lines are vestigial — they are defined but never used).
There are also human-readable `Hint:` lines (per-output mismatch counts, reset behaviour hints) that
must **not** be parsed as the verdict.

Two timeout mechanisms:
1. Inside the TB: `initial begin #1000000 $display("TIMEOUT"); $finish(); end`
   (`\`timescale 1 ps/1 ps`, 10 ps clock period ⇒ 100,000 cycles).
2. External, in the Makefile: `timeout 30 ./<binary>` and if `PIPESTATUS[0] == 124`,
   the literal string `TIMEOUT` is appended to the log.

Compile-time pass/fail signals in the log: `Unknown module type` (missing/renamed module),
`Unable to bind wire/reg` (port mismatch), `syntax error`, `is declared here as wire`, etc.

Two testbench quirks worth handling:
* `Prob156_review2015_fancytimer_test.sv` begins with **`` `default_nettype none ``** — a DUT relying on
  implicit nets will fail to compile. The harness always compiles the DUT from a *separate* file, so
  adapters should do the same rather than concatenating.
* Several TBs use `` `define OK 12 ``/`` `define INCORRECT 13 `` and `int`, `bit`, `typedef struct packed`,
  `$urandom`, `always_comb` — i.e. they require `-g2012` (SystemVerilog).
* All TBs contain a `wavedrom_start`/`wavedrom_stop` pair and a `$dumpfile("wave.vcd")` + `$dumpvars`
  call; the latter creates a `wave.vcd` in the run directory.

---

## 5. Harness mechanics

### 5a. v2 (main branch) — driven by `make`
**[VERIFIED]** `https://raw.githubusercontent.com/NVlabs/verilog-eval/main/Makefile.in`

Compile+run recipe (per problem × sample), from the `problem_template` define:

```make
$(1)_sv_iv_test_logs : %-sv-iv-test.log : %.sv $(1)_test.sv $(1)_ref.sv
	-$$(QUIET) $(IVERILOG_COMPILE) -o $$* $$^ \
               $(REDIRECT_LOG) $$*-sv-iv-test.log
	-$$(QUIET) timeout 30 ./$$* $(REDIRECT_APPEND_LOG) $$@; \
             if [[ $$$${PIPESTATUS[0]} == 124 ]]; then    \
               echo "TIMEOUT" $(REDIRECT_APPEND_LOG) $$@; \
             fi
```

with

```make
IVERILOG_COMPILE=@IVERILOG@ -Wall -Winfloop -Wno-timescale -g2012 -s tb
```

So the **exact compile command** is (expanding `$^` = `<sample>.sv <stem>_test.sv <stem>_ref.sv`):

```
iverilog -Wall -Winfloop -Wno-timescale -g2012 -s tb -o Prob001_zero_sample01 \
         Prob001_zero_sample01.sv Prob001_zero_test.sv Prob001_zero_ref.sv
```

and the **exact run command**:

```
timeout 30 ./Prob001_zero_sample01
```

* Simulator: **Icarus Verilog (`iverilog`)** only. `vvp` is invoked implicitly by the `iverilog -o`
  output being an executable script on Linux. **Verilator, Vivado xsim, VCS are not used by the harness**
  (the README mentions installing verilator, but no script calls it).
* `-g2012` = SystemVerilog 2012; `-s tb` forces the TB as top; `-Wall -Winfloop -Wno-timescale`.
* README version guidance: **iverilog v12**; *"iverilog v13 (development release) is not supported."*
* Tool path comes from `configure.ac`: `AC_CHECK_PROGS([IVERILOG],[iverilog],[no])`, erroring out if absent.

`configure.ac` generates `problems.mk` and `samples.mk` from `${dataset_dir}/problems.txt`:

```make
problems = \
  Prob001_zero \
  Prob002_m2014_q4i \
  ...
# samples.mk, one line per problem:
Prob001_zero_num_samples =  20
```

Key configure defaults **[VERIFIED]**: `--with-task=spec-to-rtl`, `--with-samples=20`,
`--with-temperature=0.85`, `--with-top-p=0.95`, `--with-examples=0`, `--with-rules=no`,
`--with-dataset=${srcdir}/dataset_${task}`, `--with-problems=${dataset_dir}/problems.txt`.
(`--with-examples=yes` is translated by the Makefile into `--examples=4`.)

Per-problem working directories are created as `<stem>/<stem>_sample<NN>.sv` plus
`<stem>_sample<NN>-sv-generate.log` and `<stem>_sample<NN>-sv-iv-test.log`.

### 5b. Pass determination in v2
**[VERIFIED]** `https://raw.githubusercontent.com/NVlabs/verilog-eval/main/scripts/sv-iv-analyze`

It does **not** use exit codes. It reads the compile/run log and regex-matches:

```python
mismatch_pattern = r'^Mismatches: (\d+) in \d+ samples$'
...
match = re.match( mismatch_pattern, line )
if match:
    num_mismatch = int(match.group(1))
    if num_mismatch == 0:
        no_mismatch = True
    else:
        result_record.num_mismatch = num_mismatch
...
if result_record.passfail == '?' and no_mismatch:
    result_record.passfail = '.'
```

Single-character verdicts emitted (**`.` = pass**):

| char | meaning (log substring it keys on) |
|---|---|
| `.` | pass — `Mismatches: 0 in N samples` |
| `S` | `syntax error` |
| `e` | `error: This assignment requires an explicit cast` |
| `0` | `error: Sized numeric constant must have a size greater than zero` |
| `n` | `warning: always_comb process has no sensitivities` / `found no sensitivities so it will never trigger` |
| `w` | `is declared here as wire` |
| `m` | `Unknown module type` |
| `c` | `Unable to bind wire/reg/memory `clk'` |
| `p` | `Unable to bind wire/reg` (generic) |
| `C` | any other line containing `error` |
| `T` | `TIMEOUT` |
| `r` | DUT source contains `posedge reset` / `negedge reset` / `posedge r)` (reset-style heuristic) |
| `R` | remaining runtime errors (uses `num_mismatch` for the Gini-Simpson diversity index) |

Aggregation: per problem it prints `[npass/nsamples](pct%)`, `pass_rate` (mean of per-problem
percentages), Gini-Simpson index, token counts, cost. `--csv=summary.csv` writes
`problem,npass,nsamples,pass_rate,<one char per sample>`. `make` default target is `sv-iv-analyze`.

### 5c. v1 (branch `release/1.0.0`) — for reference
**[VERIFIED]** `https://raw.githubusercontent.com/NVlabs/verilog-eval/release/1.0.0/verilog_eval/execution.py`

```python
verilog_test = problem["test"] + "\n" + problem["prompt"] + "\n" + completion
with open("{}.sv".format(problem["task_id"]), 'w') as f:
    f.write(verilog_test)
...
cmd = "iverilog -Wall -Winfloop -Wno-timescale -g2012 \
            -s tb -o test.vvp {}.sv; vvp -n test.vvp".format(problem["task_id"])
p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
...
out, err = out.decode("utf-8"), err.decode("utf-8")
match = re.search(r'Mismatches: ([0-9]*) in ([0-9]*) samples', out)
if "syntax error" in err:
    result.append("failed: syntax error.")
elif len(err) > 0:
    result.append("failed: compile error.")
elif match:
    cor, tot = [int(i) for i in match.groups()]
    if cor == 0:
        result.append("passed")
    else:
        result.append(f"failed: {cor} out of {tot} samples.")
else:
    result.append("failed: info string not matched.")
```

Note v1 concatenates `test + prompt + completion` into **one** `.sv` file (prompt supplies the
`module top_module (...)` header, completion supplies the body, `test` supplies everything else),
whereas v2 keeps three separate files.

### 5d. Reference model / per-cycle comparison
**[VERIFIED]** Yes — the comparison is **per half-clock-cycle**, and the reference implementation is
the sibling `_ref.sv` file (module `RefModule`) compiled into the same simulation. This is the v2
equivalent of v1's `canonical_solution` (which in v1 was textually spliced into `module reference_module`
inside the `test` string). The comparator:

```verilog
assign tb_match = ( { out_ref } === ( { out_ref } ^ { out_dut } ^ { out_ref } ) );
always @(posedge clk, negedge clk) begin
  stats1.clocks++;
  if (!tb_match) begin
    if (stats1.errors == 0) stats1.errortime = $time;
    stats1.errors++;
  end
  ...
end
```

The XOR trick plus `===` means *X in the reference matches anything, but X in the DUT only matches X*
(stated verbatim in the TB comment). Multiple DUT outputs are concatenated into one vector for
`tb_match` and also compared individually into `errors_<portname>` counters that feed the `Hint:` lines.

---

## 6. Counts and naming

**[VERIFIED]** `156` problems.
`https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/problems.txt` contains a
complete, contiguous enumeration `Prob001_zero` … `Prob156_review2015_fancytimer` (no gaps, no dups), one
stem per line. `dataset_code-complete-iccad2023/problems.txt` was fetched and is **byte-identical in
content** (same 156 stems, same order).

First and last entries:
```
Prob001_zero
Prob002_m2014_q4i
...
Prob155_lemmings4
Prob156_review2015_fancytimer
```

### `task_id` shape
* v2 has no `task_id` field. The identifier used throughout the v2 tooling is the **file stem**,
  `Prob<NNN>_<shortname>` (e.g. `Prob001_zero`, `Prob143_fsm_onehot`, `Prob156_review2015_fancytimer`).
  `sv-generate` derives the problem label as `os.path.basename(filename[:-11])`, i.e. strips the
  trailing `_prompt.txt` → `Prob001_zero`.
* **There is no `VerilogEval-v2/...` namespace prefix anywhere** in this repo. Neither in `problems.txt`,
  nor in filenames, nor in the v1 JSONL.
* v1 `task_id` is the **bare short name with no `ProbNNN_` prefix**: e.g. `"zero"`, `"gatesv"`,
  `"rotate100"`, `"review2015_fsmonehot"`, `"m2014_q4e"`, `"2012_q1g"`, `"counter_2bc"`.
  Verified from the loaded JSONL records and from `execution.py` using `problem["task_id"]` directly as
  the filename.
* **[INFERRED]** The mapping between v1 `task_id` and v2 stem is therefore
  `<NNN>` from the stem prefix + `_` + v1 `task_id`; e.g. v1 `"zero"` ↔ `Prob001_zero`.

Per-problem file/sample naming produced by the v2 harness (inside a `build/` dir):
```
Prob001_zero/Prob001_zero_sample01.sv
Prob001_zero/Prob001_zero_sample01-sv-generate.log
Prob001_zero/Prob001_zero_sample01-sv-iv-test.log
Prob001_zero/Prob001_zero_sample01        (iverilog output binary)
```
Sample numbers are zero-padded to 2 digits (`seq --format "%02g"`), so >99 samples would break the
`sample(\d{2})` regex in `sv-iv-analyze`.

---

## 7. Licensing

**[VERIFIED]** `https://raw.githubusercontent.com/NVlabs/verilog-eval/main/LICENSE` — **MIT License**,
`Copyright (c) 2023-2024 NVIDIA Research Projects`, full standard MIT text. It then appends a second
MIT block:

> This project contains code from human-eval (https://github.com/openai/human-eval/).
> The MIT License — Copyright (c) OpenAI (https://openai.com)

**No non-commercial, no-derivatives, share-alike, patent, or field-of-use restriction is present.**
Vendoring the dataset and harness into another project is permitted provided the MIT copyright notice
and permission notice are retained (both the NVIDIA and the OpenAI blocks).

### Flags / cautions before vendoring
* **[VERIFIED]** Neither `LICENSE` nor `README.md` mentions HDLBits (I read both in full).
* **[INFERRED — diligence item, not a verified restriction]** The problem stems are unmistakably
  HDLBits problem IDs (`m2014_q4i`, `ece241_2014_q1c`, `mt2015_eq2`, `lemmings1..4`, `rule90`,
  `conwaylife`, `2012_q1g`, `review2015_*`, …), and the reference solutions/testbench styles match
  HDLBits. The repo's MIT grant covers the repository contents *as published by NVIDIA*; it does not
  document any upstream attribution for HDLBits. That is a diligence matter for a legal reviewer,
  not something I could resolve from the repo.
* **[VERIFIED]** The problems are drawn from the ICCAD 2023 paper dataset; the canonical citation is
  `Liu, Pinckney, Khailany, Ren, "VerilogEval: Evaluating Large Language Models for Verilog Code
  Generation", ICCAD 2023` and for v2 `Pinckney et al., arXiv:2408.11053`.
* **[NOT VERIFIED]** I did not read `LICENSE` on branch `release/1.0.0` (blob size 2253 B vs 2257 B on
  main — almost certainly the same MIT text with a slightly different year range, but unchecked).
* Source files carry SPDX headers, e.g. `SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION
  & AFFILIATES. All rights reserved.` / `SPDX-License-Identifier: MIT`.

---

## 8. Explicitly NOT verified

* I read only 5 of the 156 testbenches (`Prob001`, `Prob050`, `Prob060`, `Prob143`, `Prob156`) plus the
  code-complete `Prob001`. All five use the identical `RefModule`/`TopModule`/`Mismatches:` convention,
  and every log-parsing rule in `sv-iv-analyze` assumes that convention, so **[INFERRED]** it holds for
  all 156 — I did not check each file.
* I did not enumerate the whole `dataset_spec-to-rtl` directory via API (the listing response was
  truncated at ~50 KB). The "469 files" figure and the "no `_ifc.txt`" claim rest on: sampled listings
  (Prob001–Prob035), two 404 probes, and the fact that only `sv-generate`'s code-complete branch ever
  reads `_ifc.txt`.
* I did not verify the 156 count with an independent API count; it comes from reading `problems.txt`
  in full (contiguous `Prob001`…`Prob156`, confirmed identical in both dataset directories).
* I did not run iverilog or the harness; all commands above are quoted from the scripts.
* `count_failures.py` and `pass_rate_to_csv.py` were listed but not read.

---

## 9. URLs fetched (for re-checking)

```
https://api.github.com/repos/NVlabs/verilog-eval/contents/
https://api.github.com/repos/NVlabs/verilog-eval/git/trees/main?recursive=1
https://api.github.com/repos/NVlabs/verilog-eval/contents/dataset_spec-to-rtl?ref=main
https://api.github.com/repos/NVlabs/verilog-eval/contents/dataset_code-complete-iccad2023?ref=main
https://api.github.com/repos/NVlabs/verilog-eval/contents/scripts?ref=main
https://api.github.com/repos/NVlabs/verilog-eval/contents/?ref=release/1.0.0
https://api.github.com/repos/NVlabs/verilog-eval/contents/data?ref=release/1.0.0
https://api.github.com/repos/NVlabs/verilog-eval/contents/verilog_eval?ref=release/1.0.0
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/README.md
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/LICENSE
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/Makefile.in
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/configure.ac
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/scripts/sv-generate
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/scripts/sv-iv-analyze
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/scripts/prompt-example-prefix.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/scripts/verilog-example-prefix_spec-to-rtl_1-shot.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/problems.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob001_zero_prompt.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob001_zero_ref.sv
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob001_zero_test.sv
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob002_m2014_q4i_prompt.txt   (attempted)
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob032_vector0_prompt.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob050_kmap1_test.sv
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob060_m2014_q4k_test.sv
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob090_circuit1_prompt.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob137_fsm_serial_prompt.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob143_fsm_onehot_test.sv
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob156_review2015_fancytimer_test.sv
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob001_zero_ifc.txt          -> 404
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl/Prob032_vector0_ifc.txt        -> 404
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_code-complete-iccad2023/problems.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_code-complete-iccad2023/Prob001_zero_ifc.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_code-complete-iccad2023/Prob001_zero_prompt.txt
https://raw.githubusercontent.com/NVlabs/verilog-eval/release/1.0.0/data/VerilogEval_Human.jsonl
https://raw.githubusercontent.com/NVlabs/verilog-eval/release/1.0.0/verilog_eval/data.py
https://raw.githubusercontent.com/NVlabs/verilog-eval/release/1.0.0/verilog_eval/execution.py
https://raw.githubusercontent.com/NVlabs/verilog-eval/release/1.0.0/verilog_eval/evaluation.py
```
