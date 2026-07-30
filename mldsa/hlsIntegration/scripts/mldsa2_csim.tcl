set parent_dir [pwd]
open_project mldsa_test
set_top mldsa_accelerator
add_files k_dsa.cpp
add_files kernel.hpp -cflags -DDILITHIUM_MODE=2
add_files -tb testbench/tb_mldsa.cpp -cflags -DDILITHIUM_MODE=2
open_solution "csim" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 200MHz -name default
csim_design
exit
