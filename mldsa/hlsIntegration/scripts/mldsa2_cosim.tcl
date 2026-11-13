# RTL co-simulation of the reduced NIST set (testbench/tb_vectors_cosim.h), Vitis HLS 2025.2: csynth with the settings of scripts/mldsa2.tcl,
# so that the RTL under test is the RTL that is exported, then cosim (about 30 min). Run from hlsIntegration/:
#   vitis-run --mode hls --tcl scripts/mldsa2_cosim.tcl
open_project -reset mldsa_test_cosim
set_top mldsa_accelerator
add_files k_dsa.cpp -cflags "-DDILITHIUM_MODE=2"
add_files kernel.hpp
add_files -tb testbench/tb_mldsa_cosim.cpp -cflags "-DDILITHIUM_MODE=2"
open_solution -reset "cosim" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 200MHz -name default
config_dataflow -fifo_depth 100
config_interface -m_axi_addr64=0 -m_axi_conservative_mode
config_rtl -reset state -deadlock_detection none
csynth_design
cosim_design
exit
