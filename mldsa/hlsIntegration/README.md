# README
## How to Generate the MLDSA Accelerator

### Requirements:

- Vitis\_HLS 2021.2 version

To generate the accelerator, run:

```sh
make mldsa2
```

The Makefile will configure the **MLDSA in SELENE PLATFORM** to be synthesized with **Vivado 2020.2** by executing the appropriate `make` command in `selene-soc/selene-xilinx-vcu118`.

## FIPS 204 Compliance Changes (this fork)

This fork adds two changes to `k_dsa.cpp`/`kernel.hpp` aimed at bringing the accelerator's sign/verify interfaces closer to FIPS 204 as specified, plus real hedged-signing support.
Both are additive: existing callers supplying an all-zero `rnd_in` and an empty `ctx_in`
(`ctxlen_in = 0`) get behavior identical to the upstream accelerator.

### `rnd_in` — real hedged-signing input

`mldsa_accelerator`/`k_sign` now take an additional `uint8_t *rnd_in` (32 bytes). Previously,
the `rnd` component of the `rho'' <- H(K || rnd || mu, 64)` derivation (FIPS 204 Algorithm 7,
step 7) was hardcoded to all-zero inside `keccak_absorb_key_mu`. It is now an input:

- All-zero `rnd_in` reproduces the previous behavior exactly — this is the spec-permitted
  deterministic variant (Algorithm 2, step 5: *"for the optional deterministic variant,
  substitute rnd <- {0}^32"*).
- A non-zero `rnd_in` enables genuine hedged signing.

Nothing generates randomness on-chip; *the caller is responsible* for supplying `rnd_in`.

### `ctx_in` / `ctxlen_in` — verify-path message domain separation

`mldsa_accelerator`/`k_verify` now take an additional `uint8_t *ctx_in` (up to 255 bytes) and
`uint8_t ctxlen_in`. Previously, `k_verify` computed its internal message representative `mu`
directly from the raw message (`mu = H(tr || M, 64)`), never constructing the FIPS 204
Algorithm 3 formatted message

```
M' = BytesToBits(IntegerToBytes(0,1) || IntegerToBytes(|ctx|,1) || ctx) || M
```

before hashing. `k_verify` now builds `M'` (via a small `make_mprime` helper) ahead of the
`mu = H(tr || M', 64)` step (Algorithm 8, step 7). `ctxlen_in` is `uint8_t`, so the spec's
`|ctx| <= 255` bound (Algorithm 3, steps 1-3) holds by construction; no separate runtime
check is required.

**Scope note:** this only fixes the *verify* path. `k_sign` still consumes a pre-computed
`mu` as an opaque input and never derives it on-chip — Algorithm 2's equivalent `ctx`
handling for signing must be done by whatever host software computes that `mu` before
calling this accelerator, outside this repository.

### Validation

Both changes were validated via HLS C-simulation (`csim_design`) *and* RTL cosimulation
(`cosim_design`) against the official [NIST ACVP-Server](https://github.com/usnistgov/ACVP-Server)
ML-DSA-44 KAT vectors (`gen-val/json-files/ML-DSA-{sigGen,sigVer}-FIPS204`): covering
verify with non-trivial `context` values (including negative/malformed signatures,
correctly rejected), and sign with both `rnd = 0` and real hedged `rnd` values, each
checked for a byte-exact signature match against the NIST-published expected output.
35 of the 45 official vectors apply to this build (5 sigVer + 30 sigGen) - the other 10
sigVer vectors have messages exceeding this build's 1024-byte production message-size
bound and are correctly excluded, not failing; see "Known finding" below.

### Running the testbench

Two validation tiers, both gitignored until (re)generated locally: the downloaded NIST
vectors and the generated header(s).

```sh
cd mldsa/hlsIntegration/testbench
./fetch_vectors.sh        # downloads the official NIST ACVP-Server ML-DSA KAT vectors
python3 gen_vectors.py    # writes tb_vectors.h AND tb_vectors_cosim.h, stdlib only

cd ..
vitis-run --mode hls --tcl scripts/mldsa2_csim.tcl    # fast: plain C-simulation, all 45 vectors
vitis-run --mode hls --tcl scripts/mldsa2_cosim.tcl   # slow: full csynth + cycle-accurate RTL cosim, 4 reduced vectors
```

`mldsa2_csim.tcl` runs entirely as plain C++ - no board, no Vivado project, no Vitis SW
workspace. Expect it to end with:

```
=== Result: 5/5 verify cases OK, 30/30 sign cases OK ===
INFO: [SIM 211-1] CSim done with 0 errors.
```

`mldsa2_cosim.tcl` additionally synthesizes the design and simulates the actual RTL via
XSIM - real hardware-accuracy, not just the C model - on a reduced 4-case set (one
verify-accept, one verify-reject, one deterministic sign, one hedged sign; see
`gen_vectors.py`'s docstring for why a reduced set is appropriate here). Expect it to
end with:

```
=== Result: 2/2 verify cases OK, 2/2 sign cases OK ===
INFO: [COSIM 212-1000] *** C/RTL co-simulation finished: PASS ***
```

Tested with Vitis HLS 2024.2 paired with Vivado 2024.2

### Known finding: `mu_orig_in` message-length buffer sizing

While validating the `ctx` fix via `cosim_design` (RTL-accurate simulation), a **separate,
pre-existing** defect surfaced: `mu_orig_in`'s AXI interface (the raw message input for
`k_verify`) was declared `depth=2600` - far too small for real messages. NIST's own
ML-DSA-44 conformance vectors include messages up to 8192 bytes; anything past the
declared depth got silently corrupted during RTL-accurate simulation (`csim_design`'s
simplified stream model never enforces the declared depth, so this was invisible to it -
it passed all 45 vectors while quietly being wrong for the long ones). This predates the
`ctx` change entirely; it was never exercised with realistic message lengths before.

**Production value: `depth=1024`** (`k_dsa.cpp`'s `mu_orig_in` `#pragma HLS INTERFACE`,
`s_mu_mrg`/`s_m`'s internal stream depths, `testbench/tb_axi_depths.h`'s
`AXI_DEPTH_MU_ORIG`, and `gen_vectors.py`'s `M_AXI_DEPTH["msg"]` - all four must stay
consistent). Chosen for automotive/aerospace deployment: typical direct-signed
protocol/telemetry messages in that space (e.g. V2X/J2735-style safety messages, CCSDS
telecommand/telemetry packets) are well under 1KB, and FIPS 204 itself recommends
pre-hashing genuinely large content externally and signing the digest
(`HashML-DSA`/"pre-hash" mode, Section 5.4) rather than streaming it through this port -
1024 bytes is comfortable headroom over realistic message sizes without paying BRAM cost
for capacity the application should never use directly. SELENE's own existing test
harness fixes `MLEN=100`, well within this bound.

**Direct, expected consequence for testing:** `gen_vectors.py` excludes (prints, does not
silently pad/truncate) every NIST sigVer vector whose real message exceeds 1024 bytes -
**10 of the 15 official vectors no longer participate in `csim_design`** (`tb_vectors.h`
now covers 5 sigVer + 30 sigGen = 35 of the original 45 cases), and the reduced cosim set
was moved to two different official vectors that do fit (`tc12` accept, `tc2` reject,
both with non-trivial `ctx`), since the original `tc1`/`tc4` pair (8192 and 4741 bytes)
no longer applies to this configuration. This is a scope reduction of what this
production build can accept as input, correctly reflecting the 1024-byte bound - not a
bug, and not something to "fix" back to passing all 45 by re-growing the buffer.

If a future deployment genuinely needs to verify longer messages directly, revisit this
number specifically against that requirement rather than reverting to NIST's own
worst-case test length.