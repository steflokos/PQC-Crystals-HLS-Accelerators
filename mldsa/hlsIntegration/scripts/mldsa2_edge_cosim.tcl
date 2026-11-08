# RTL co-simulation of the reduced edge-case set (4 sign + 6 verify cases) with the settings of scripts/mldsa2.tcl. Run from this folder:
#   vitis-run --mode hls --tcl scripts/mldsa2_edge_cosim.tcl      (csynth about 10 min, then the simulation)
set parent_dir [pwd]
open_project mldsa_test_edge_cosim
set_top mldsa_accelerator
add_files k_dsa.cpp
add_files kernel.hpp -cflags -DDILITHIUM_MODE=2
add_files -tb testbench/tb_edge.cpp -cflags "-DDILITHIUM_MODE=2 -DEDGE_COSIM"
open_solution "edge_cosim" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 100MHz -name default
# The settings below are those of scripts/mldsa2.tcl, so that the RTL under test is the RTL that is exported.
config_dataflow -fifo_depth 100
config_interface -m_axi_addr64=0 -m_axi_conservative_mode
config_rtl -reset state -deadlock_detection none
csynth_design
cosim_design
exit
