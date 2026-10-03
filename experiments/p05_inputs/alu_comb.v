`timescale 1ns/1ps

module alu_comb (
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire       sub,
    output wire [7:0] y
);
    assign y = sub ? (a - b) : (a + b);
endmodule
