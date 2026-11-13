# C simulation of the edge-case set (testbench/tb_edge.cpp; vectors from testbench/gen_edge.py), Vitis HLS 2025.2. Run from hlsIntegration/:
#   vitis-run --mode hls --tcl scripts/mldsa2_edge_csim.tcl
open_project -reset mldsa_test_edge
set_top mldsa_accelerator
add_files k_dsa.cpp -cflags "-DDILITHIUM_MODE=2"
add_files kernel.hpp
add_files -tb testbench/tb_edge.cpp -cflags "-DDILITHIUM_MODE=2"
open_solution -reset "edge" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 200MHz -name default
csim_design
exit
