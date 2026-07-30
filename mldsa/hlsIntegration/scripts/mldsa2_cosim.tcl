set parent_dir [pwd]
open_project mldsa_test_cosim
set_top mldsa_accelerator
add_files k_dsa.cpp
add_files kernel.hpp -cflags -DDILITHIUM_MODE=2
add_files -tb testbench/tb_mldsa_cosim.cpp -cflags -DDILITHIUM_MODE=2
open_solution "cosim" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 200MHz -name default
# See mldsa2.tcl: default reset level doesn't reset static-variable-derived
# registers (every hls::stream here), letting residue leak across invocations.
config_rtl -reset state
csynth_design
cosim_design
exit
