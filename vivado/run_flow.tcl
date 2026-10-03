if {[llength $argv] < 5} {
    puts "Usage: vivado -mode batch -source run_flow.tcl -tclargs <rtl> <tb> <tb_top> <top> <run_dir>"
    exit 2
}

set rtl_path [file normalize [lindex $argv 0]]
set tb_path [file normalize [lindex $argv 1]]
set tb_top [lindex $argv 2]
set top [lindex $argv 3]
set run_dir [file normalize [lindex $argv 4]]
set target_part "xczu3eg-sbva484-1-e"
if {[info exists ::env(LOGICLENS_TARGET_PART)] && $::env(LOGICLENS_TARGET_PART) ne ""} {
    set target_part $::env(LOGICLENS_TARGET_PART)
}
file mkdir $run_dir
cd $run_dir

# Vivado 2025.2 xsim can fail to create its Windows file-mapping object on
# some secondary/work drives. Keep transient simulator state on the system
# temporary drive while preserving all evidence under run_dir. TMPDIR/TMP/TEMP
# are tried in that order so the same script works in a Linux container.
set sim_root ""
foreach env_name {TMPDIR TMP TEMP} {
    if {[info exists ::env($env_name)] && $::env($env_name) ne "" && [file isdirectory $::env($env_name)]} {
        set sim_root $::env($env_name)
        break
    }
}
if {$sim_root eq ""} {
    set sim_root [file join $run_dir ".sim"]
}
set sim_dir [file join $sim_root [format "LogicLensSim_%d" [pid]]]
file mkdir $sim_dir

proc append_log {name content} {
    set fd [open $name w]
    puts $fd $content
    close $fd
}

# Collapse all whitespace runs into single spaces so port detection can rely on
# plain substring tests instead of regexes with shell-hostile quoting.
proc normalize_ws {text} {
    return [regsub -all {\s+} $text " "]
}

# The competition fixes a 5 ns clock, but several spec-to-rtl tasks are purely
# combinational and have no clock port at all. Applying an unclockable
# constraint there would silently drop the clock and then fail the constraint
# check, so only clocked designs receive the XDC.
set clk_port ""
set rtl_fd [open $rtl_path r]
set rtl_norm [normalize_ws [read $rtl_fd]]
close $rtl_fd
foreach candidate {clk clock clk_i clock_i i_clk} {
    set decl_forms [list \
        "input ${candidate} " "input ${candidate}," "input ${candidate})" \
        "input wire ${candidate} " "input wire ${candidate}," "input wire ${candidate})" \
        "input reg ${candidate} " "input reg ${candidate}," "input reg ${candidate})" \
        "input logic ${candidate} " "input logic ${candidate}," "input logic ${candidate})" \
        "input bit ${candidate} " "input bit ${candidate}," "input bit ${candidate})"]
    set found 0
    foreach form $decl_forms {
        if {[string first $form " $rtl_norm"] >= 0} {
            set found 1
            break
        }
    }
    if {!$found && [string first ", input ${candidate}" $rtl_norm] >= 0} {
        # Handles declarations where the name is written before the direction.
        set found 1
    }
    if {$found} {
        set clk_port $candidate
        break
    }
}

if {$clk_port ne ""} {
    set xdc_path [file join $run_dir logiclens_clock.xdc]
    set xdc_fd [open $xdc_path w]
    puts $xdc_fd [format {create_clock -name clk -period 5.000 [get_ports %s]} $clk_port]
    close $xdc_fd
} else {
    set xdc_path ""
}

set compile_pass 0
set elaborate_pass 0
set simulation_pass 0
set synthesis_pass 0
set synthesis_attempted 0
set synthesis_error ""
set sim_crashed 0
set timing_constraint_pass 0

cd $sim_dir
set compile_log ""
if {[catch {set compile_log [exec xvlog -sv $rtl_path $tb_path 2>@1]} err]} {
    set compile_log "$compile_log\n$err"
} else {
    set compile_pass 1
}
append_log [file join $run_dir compile.log] $compile_log
append_log [file join $run_dir compile.pass] $compile_pass

set sim_log ""
if {$compile_pass} {
    set xelab_log ""
    set xsim_log ""
    if {[catch {set xelab_log [exec xelab -debug typical -mt off $tb_top -s logiclens_sim 2>@1]} err]} {
        set xelab_log "$xelab_log\n$err"
    } else {
        set elaborate_pass 1
    }
    if {$elaborate_pass} {
        # A non-zero catch code here means xsim itself died, not that the
        # testbench reported a mismatch. The two are recorded separately so a
        # simulator crash is never charged to the design under test.
        if {[catch {set xsim_log [exec xsim logiclens_sim -runall 2>@1]} err]} {
            set xsim_log "$xsim_log\n$err"
            set sim_crashed 1
        }
    }
    append_log [file join $run_dir elaboration.log] $xelab_log
    append_log [file join $run_dir elaboration.pass] $elaborate_pass
    set sim_log $xsim_log

    # Automated testbenches signal success with TEST_PASS. A design must never
    # be credited for simulation it did not reach, and a bare "error" substring
    # must not decide the outcome: a correct design may legitimately print that
    # word. Only the unambiguous simulator failure markers are treated as a
    # failure signal here.
    if {!$sim_crashed && [string first "test_pass" [string tolower $sim_log]] >= 0 &&
        ![regexp -nocase {(?:^|\s)(?:ERROR:|Fatal:)} $sim_log]} {
        set simulation_pass 1
    }
}
append_log [file join $run_dir simulation.log] $sim_log
append_log [file join $run_dir simulation.pass] $simulation_pass

# Progressive grading: the competition only advances to the next level when
# the previous level passed. Synthesis is therefore gated on simulation, and
# when it is skipped synthesis_pass stays 0 while synthesis_attempted records
# that the netlist was never produced - so per-level reporting cannot mistake
# "not run" for "ran and passed".
set synth_log ""
set synthesis_attempted 0
if {$compile_pass && $simulation_pass} {
    set synthesis_attempted 1
    if {[catch {
        read_verilog -sv $rtl_path
        if {$xdc_path ne ""} {
            read_xdc $xdc_path
        }
        synth_design -top $top -part $target_part
        report_utilization -file [file join $run_dir utilization.rpt]
        set timing_report [file join $run_dir timing.rpt]
        report_timing_summary -file $timing_report
        set timing_fd [open $timing_report r]
        set timing_text [read $timing_fd]
        close $timing_fd
        # A combinational task has no clock to constrain, so the check is only
        # applicable when a clock port was found and the XDC was generated.
        if {$xdc_path eq ""} {
            set timing_constraint_pass 1
        } elseif {[string first "There are no user specified timing constraints." $timing_text] < 0 &&
                  [string first "unconstrained_internal_endpoints (0)" $timing_text] >= 0 &&
                  [string first "Clock Summary" $timing_text] >= 0} {
            set timing_constraint_pass 1
        }
    } err]} {
        set synth_log "$synth_log\n$err"
        set error_text [string map {"\n" " " "\r" " " "\"" "'" "\\" "/"} [string trim $err]]
        set synthesis_error [string range $error_text 0 300]
        set synthesis_pass 0
    } else {
        set synthesis_pass 1
    }
}
append_log [file join $run_dir synthesis.log] $synth_log
append_log [file join $run_dir synthesis.pass] $synthesis_pass

set summary "{\n  \"compile_pass\": $compile_pass,\n  \"elaborate_pass\": $elaborate_pass,\n  \"simulation_pass\": $simulation_pass,\n  \"sim_crashed\": $sim_crashed,\n  \"synthesis_attempted\": $synthesis_attempted,\n  \"synthesis_pass\": $synthesis_pass,\n  \"synthesis_error\": \"$synthesis_error\",\n  \"timing_constraint_pass\": $timing_constraint_pass,\n  \"clock_port\": \"$clk_port\",\n  \"target_part\": \"$target_part\",\n  \"clock_period_ns\": 5.0,\n  \"timing_constraint_file\": \"logiclens_clock.xdc\",\n  \"tool\": \"vivado\"\n}"
append_log [file join $run_dir flow_result.json] $summary
exit 0
