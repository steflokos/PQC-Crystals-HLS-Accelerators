set parent_dir [pwd]
open_project mldsa_test_cosim
set_top mldsa_accelerator
add_files k_dsa.cpp
add_files kernel.hpp -cflags -DDILITHIUM_MODE=2
add_files -tb testbench/tb_mldsa_cosim.cpp -cflags -DDILITHIUM_MODE=2
open_solution "cosim" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 100MHz -name default
# The settings below are those of scripts/mldsa2.tcl, so that the RTL under test is the RTL that is exported.
config_dataflow -fifo_depth 100
config_interface -m_axi_addr64=0 -m_axi_conservative_mode
# See mldsa2.tcl: kept as a precaution; it has no effect on the generated RTL of this design.
config_rtl -reset state -deadlock_detection none
csynth_design
cosim_design
exit
