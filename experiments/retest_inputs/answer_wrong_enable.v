`timescale 1ns/1ps

module counter (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       enable,
    output reg [7:0]  count
);
    always @(posedge clk) begin
        if (!rst_n) begin
            count <= 8'd0;
        end else begin
            // Deliberately wrong: this ignores enable and must fail hold check.
            count <= count + 8'd1;
        end
    end
endmodule
