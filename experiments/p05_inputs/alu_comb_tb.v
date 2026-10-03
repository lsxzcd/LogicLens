`timescale 1ns/1ps

// A purely combinational testbench: no clock is ever driven, which is the
// case that used to lose its 5 ns constraint silently.
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

        $display("TEST_PASS");
        $finish;
    end
endmodule
