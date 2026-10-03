`timescale 1ns/1ps

// Sidecar testbench for the combinational alu_comb task. Dropping this next to
// alu_comb.txt is all it takes for the flow to use it instead of generating
// one, which is how the VerilogEval harness gets attached.
module alu_comb_tb;
    reg  [7:0] a;
    reg  [7:0] b;
    reg        sub;
    wire [7:0] y;

    alu_comb dut (.a(a), .b(b), .sub(sub), .y(y));

    initial begin
        a = 8'd3; b = 8'd5; sub = 1'b0;
        #1;
        if (y !== 8'd8) $fatal(1, "add check failed");

        a = 8'd6; b = 8'd5; sub = 1'b1;
        #1;
        if (y !== 8'd1) $fatal(1, "sub check failed");

        a = 8'd0; b = 8'd0; sub = 1'b0;
        #1;
        if (y !== 8'd0) $fatal(1, "zero check failed");

        $display("TEST_PASS");
        $finish;
    end
endmodule
