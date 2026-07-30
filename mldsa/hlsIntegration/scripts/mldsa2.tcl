set parent_dir [pwd]
open_project mldsa
set_top mldsa_accelerator
#Check
add_files k_dsa.cpp
add_files kernel.hpp -cflags -DDILITHIUM_MODE=2
open_solution "mldsa2" -flow_target vivado
set_part {xcu280-fsvh2892-2L-e}
create_clock -period 300MHz -name default
config_dataflow -fifo_depth 100
config_export -deadlock_detection none -format ip_catalog -ipname mldsa_accelerator_2 -output $parent_dir/mldsa/mldsa2 -rtl verilog -version 0.0.1 -vivado_clock 300MHz
config_interface -m_axi_addr64=0 -m_axi_conservative_mode
# Default reset level ("control") only resets control/FSM registers on ap_start; it
# does NOT reset registers/memories derived from static local variables - including
# every hls::stream in this design (all declared `static` for cross-invocation
# dataflow pipelining). Without this, residual data left in a stream by one
# invocation can leak into the next repeated call. "state" covers control +
# static/global-derived registers (see cosim diagnosis, mldsa-thesis session log).
config_rtl -reset state
set_directive_top -name mldsa_accelerator "mldsa_accelerator"
csynth_design
export_design -flow syn -rtl verilog -format ip_catalog -output $parent_dir/mldsa/mldsa2
exit
