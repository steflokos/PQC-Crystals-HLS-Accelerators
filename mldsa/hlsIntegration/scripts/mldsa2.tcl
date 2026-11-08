set parent_dir [pwd]
open_project mldsa
set_top mldsa_accelerator
#Check
add_files k_dsa.cpp
add_files kernel.hpp -cflags -DDILITHIUM_MODE=2
open_solution "mldsa2" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 100MHz -name default
config_dataflow -fifo_depth 100
config_export -deadlock_detection none -format ip_catalog -ipname mldsa_accelerator_2 -output $parent_dir/mldsa/mldsa2 -rtl vhdl -version 1.0.0 -vivado_clock 100MHz
config_interface -m_axi_addr64=0 -m_axi_conservative_mode
# Precaution, kept just to be sure: the level "state" also resets registers/memories derived from
# static/global variables (every hls::stream here is static), which the default level ("control")
# leaves alone, so that a repeated call could not see residue of the previous one. It has no effect on
# the generated RTL of this design: the same source gives byte-identical VHDL with and without it
# (checked 2026-11-08).
config_rtl -reset state
set_directive_top -name mldsa_accelerator "mldsa_accelerator"
csynth_design
export_design -flow syn -rtl vhdl -format ip_catalog -output $parent_dir/mldsa/mldsa2
exit
