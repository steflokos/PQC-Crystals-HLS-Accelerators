# C simulation of the edge-case set (testbench/tb_edge.cpp; vectors from testbench/gen_edge.py). Run from this folder:
#   vitis-run --mode hls --tcl scripts/mldsa2_edge_csim.tcl
set parent_dir [pwd]
open_project mldsa_test_edge
set_top mldsa_accelerator
add_files k_dsa.cpp
add_files kernel.hpp -cflags -DDILITHIUM_MODE=2
add_files -tb testbench/tb_edge.cpp -cflags -DDILITHIUM_MODE=2
open_solution "edge" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 100MHz -name default
csim_design
exit
