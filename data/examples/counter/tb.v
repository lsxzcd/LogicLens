`timescale 1ns/1ps

module counter_tb;
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg enable = 1'b0;
    wire [7:0] count;

    counter dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .count(count)
    );

    always #5 clk = ~clk;

    initial begin
        #12;
        if (count !== 8'd0) $fatal(1, "reset check failed");

        rst_n = 1'b1;
        enable = 1'b1;
        @(posedge clk);
        #1;
        if (count !== 8'd1) $fatal(1, "first count failed");

        @(posedge clk);
        #1;
        if (count !== 8'd2) $fatal(1, "second count failed");

        enable = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 8'd2) $fatal(1, "hold check failed");

        $display("TEST_PASS");
        $finish;
    end
endmodule

