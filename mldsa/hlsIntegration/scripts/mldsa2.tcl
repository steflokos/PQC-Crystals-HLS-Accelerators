# Synthesis and export of the ML-DSA accelerator, Vitis HLS 2025.2. Run from hlsIntegration/:  vitis-run --mode hls --tcl scripts/mldsa2.tcl
# The unmodified upstream IP is synthesised with the same settings for the comparison (version 0.0.1); only -version differs.
# -reset on open_project/open_solution discards the settings and results of an earlier run of this project. The exporter does not
# overwrite older files in mldsa/mldsa2/impl, so delete mldsa/ before a run whose reports are used.
set parent_dir [pwd]
open_project -reset mldsa
set_top mldsa_accelerator
# The mode macro on the file that is compiled (a flag on a header is never used); kernel.hpp defaults to mode 2 anyway.
add_files k_dsa.cpp -cflags "-DDILITHIUM_MODE=2"
add_files kernel.hpp
open_solution -reset "mldsa2" -flow_target vivado
set_part {xcku040-sfva784-1-c}
create_clock -period 200MHz -name default
# Default depth of the dataflow channels that have no STREAM depth pragma.
config_dataflow -fifo_depth 100
# 32-bit AXI addresses (MicroBlaze V SoC); conservative AXI writes (the setting the IP was verified with).
config_interface -m_axi_addr64=0 -m_axi_conservative_mode
# reset=state also resets registers initialised from static variables; deadlock detection off (the default "sim" only instruments the
# simulation models).
config_rtl -reset state -deadlock_detection none
# VHDL IP catalog; -flow syn runs Vivado out-of-context synthesis for the utilisation and timing reports.
config_export -format ip_catalog -rtl vhdl -ipname mldsa_accelerator_2 -version 1.0.0 -vivado_clock 200MHz -flow syn -output $parent_dir/mldsa/mldsa2
csynth_design
# -flow repeated here on purpose: the out-of-context synthesis must run even if a tool version ignores the config_export default.
export_design -flow syn
exit
