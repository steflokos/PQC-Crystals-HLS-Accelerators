# C simulation of the NIST vectors (testbench/tb_vectors.h from gen_vectors.py), Vitis HLS 2025.2. Plain C++, about 10 s. Run from hlsIntegration/:
#   vitis-run --mode hls --tcl scripts/mldsa2_csim.tcl
open_project -reset mldsa_test
set_top mldsa_accelerator
add_files k_dsa.cpp -cflags "-DDILITHIUM_MODE=2"
add_files kernel.hpp
add_files -tb testbench/tb_mldsa.cpp -cflags "-DDILITHIUM_MODE=2"
open_solution -reset "csim" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 200MHz -name default
csim_design
exit
