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

This fork brings the accelerator's sign/verify interfaces closer to FIPS 204 as specified,
plus real hedged-signing support. The `rnd_in`/`ctx_in` additions below are additive -
existing callers supplying an all-zero `rnd_in` and an empty `ctx_in` (`ctxlen_in = 0`) get
behavior identical to the upstream accelerator. The on-chip sign-path mu derivation
further down, however, **removes** `mu_processed_in`/`mu2_processed_in` and replaces them
with a raw-message input (`sign_m_in`) - this is an interface-breaking change for any
caller that was supplying a pre-computed `mu`, not an additive one; see that section.

### `rnd_in` — real hedged-signing input

`mldsa_accelerator`/`k_sign` now take an additional `uint8_t *rnd_in` (32 bytes). Previously,
the `rnd` component of the `rho'' <- H(K || rnd || mu, 64)` derivation (FIPS 204 Algorithm 7,
step 7) was hardcoded to all-zero inside `keccak_absorb_key_mu`. It is now an input:

- All-zero `rnd_in` reproduces the previous behavior exactly — this is the spec-permitted
  deterministic variant (Algorithm 2, step 5: *"for the optional deterministic variant,
  substitute rnd <- {0}^32"*).
- A non-zero `rnd_in` enables genuine hedged signing.

Nothing generates randomness on-chip; *the caller is responsible* for supplying `rnd_in`.

### `ctx_in` / `ctxlen_in` — message domain separation (verify and sign)

`mldsa_accelerator` takes an additional `uint8_t *ctx_in` (up to 255 bytes) and
`uint8_t ctxlen_in`, shared between the verify and sign branches (`kem_cfg` selects
exactly one per invocation, so there's no real conflict - the same sharing already used
for `ret_out`/`ver_out` on `bundle=gmemout`). Both `k_verify` and `k_sign` build the FIPS
204 Algorithm 3 formatted message

```
M' = BytesToBits(IntegerToBytes(0,1) || IntegerToBytes(|ctx|,1) || ctx) || M
```

(via the shared `make_mprime` helper) ahead of `mu = H(tr || M', 64)` (Algorithm 8, step
7), instead of hashing the raw message directly. `ctxlen_in` is `uint8_t`, so the spec's
`|ctx| <= 255` bound (Algorithm 3, steps 1-3) holds by construction; no separate runtime
check is required.

### On-chip `tr`/`M'`/`mu` derivation for `k_sign`

`k_sign` previously took a pre-computed `mu`/`mu2` (both the same 64-byte digest, supplied
twice because HLS streams are single-consumer) as an opaque input — it never had access to
the raw message, `tr`, or `ctx`, so all of Algorithm 2's message formatting had to happen
in whatever host software called this accelerator. `k_sign` now takes a raw message instead
(`sign_m_in`, `mlen_in`) and derives everything on-chip, mirroring `k_verify`'s existing
architecture:

- **`tr`**: unpacked directly from `sk_in` (`unpack_sk`'s `TRBYTES` loop, previously
  discarded with `uint8_t discard = s_sk.read();` since nothing consumed it - now routed
  into a real stream). FIPS 204's `sk = rho || K || tr || s1 || s2 || t0` (Algorithm 6)
  already stores `tr`, so no hash is needed here, unlike `k_verify` which must compute
  `tr = H(pk)` fresh since verify never has more than the public key.
- **`M'`**: built via the same `make_mprime` helper `k_verify` uses.
- **`mu`**: a new `shake_sign_mprime` function (mirrors `shakeVer`'s structure, built from
  this file's non-Ver/sign-path `keccak_absorb`/`keccak_finalize`/`keccak_squeeze`
  primitives, which already existed for other sign-path hashes) computes
  `mu = H(tr || M', 64)`. The result is split into the two streams the rest of
  `dataflow()` already expected (`s_mu_0` for the `rho''` derivation, `s_mu_1` for the
  challenge hash) via the existing `duplicate` helper, instead of reading two identical
  copies from an external pointer.

**Interface change:** `mu_processed_in` and `mu2_processed_in` are removed entirely -
`mldsa_accelerator`'s signature changed (see `kernel.hpp`). This is **not** additive like
`rnd_in`/`ctx_in` above: any caller supplying a pre-computed `mu` must be updated to supply
the raw message instead. `sign_m_in` shares `bundle=gmemm` with `mu_orig_in` (mutually
exclusive per `kem_cfg`, same sharing pattern as `ret_out`/`ver_out`) and the same
1024-byte production message-size bound (see "Known finding" below) - it is not a
separately-sized port.

### Validation

All changes were validated via HLS C-simulation (`csim_design`) *and* RTL cosimulation
(`cosim_design`) against the official [NIST ACVP-Server](https://github.com/usnistgov/ACVP-Server)
ML-DSA-44 KAT vectors (`gen-val/json-files/ML-DSA-{sigGen,sigVer}-FIPS204`): covering
verify with non-trivial `context` values (including negative/malformed signatures,
correctly rejected), and sign with both `rnd = 0` and real hedged `rnd` values - now driven
by raw `(message, ctx)` inputs through the on-chip derivation above, not pre-computed `mu`
- each checked for a byte-exact signature match against the NIST-published expected
output. sigGen vectors come from the ACVP-Server's *external* groups (tgId=1 deterministic,
tgId=13 hedged - message+context+sk, mirroring sigVer's own external tgId=1), not the
*internal* groups (tgId=7/19, mu+sk) used before the mu-processed interface was removed.
12 of the 45 official vectors apply to this build (5 sigVer + 3 deterministic sigGen + 4
hedged sigGen) - the rest have messages exceeding this build's 1024-byte production
message-size bound and are correctly excluded, not failing. This is a smaller applicable
fraction than the previous 35/45: sign's real message-length exposure is new (the old
internal/mu-based sigGen vectors had no message field to filter, since `mu` is always a
fixed 64 bytes regardless of real message length) - the reduction reflects sign now being
honestly subject to the same bound verify already was, not a regression; see "Known
finding" below.

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
=== Result: 5/5 verify cases OK, 7/7 sign cases OK ===
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

### Known finding: message-length buffer sizing (`mu_orig_in` / `sign_m_in`)

While validating the `ctx` fix via `cosim_design` (RTL-accurate simulation), a **separate,
pre-existing** defect surfaced: `mu_orig_in`'s AXI interface (the raw message input for
`k_verify`) was declared `depth=2600` - far too small for real messages. NIST's own
ML-DSA-44 conformance vectors include messages up to 8192 bytes; anything past the
declared depth got silently corrupted during RTL-accurate simulation (`csim_design`'s
simplified stream model never enforces the declared depth, so this was invisible to it -
it passed all 45 vectors while quietly being wrong for the long ones). This predates the
`ctx` change entirely; it was never exercised with realistic message lengths before.
`sign_m_in` (the raw message input for `k_sign`, added once `k_sign` started deriving
`tr`/`M'`/`mu` on-chip instead of taking a pre-computed `mu`) is subject to the exact same
sizing concern and was given the same bound from the start.

**Production value: `depth=1024`**, consistent across seven places: `k_dsa.cpp`'s
`mu_orig_in` and `sign_m_in` `#pragma HLS INTERFACE`, the `s_mu_mrg`/`s_m` (verify) and
`s_mu_mrg_sign`/`s_m_sign` (sign) internal stream depths, `testbench/tb_axi_depths.h`'s
`AXI_DEPTH_MU_ORIG`/`AXI_DEPTH_SIGN_M`, and `gen_vectors.py`'s `M_AXI_DEPTH["msg"]`. Chosen
for automotive/aerospace deployment: typical direct-signed protocol/telemetry messages in
that space (e.g. V2X/J2735-style safety messages, CCSDS telecommand/telemetry packets) are
well under 1KB, and FIPS 204 itself recommends pre-hashing genuinely large content
externally and signing the digest (`HashML-DSA`/"pre-hash" mode, Section 5.4) rather than
streaming it through this port - 1024 bytes is comfortable headroom over realistic message
sizes without paying BRAM cost for capacity the application should never use directly.
SELENE's own existing test harness fixes `MLEN=100`, well within this bound.

**Direct, expected consequence for testing:** `gen_vectors.py` excludes (prints, does not
silently pad/truncate) every NIST vector whose real message exceeds 1024 bytes - this now
applies to sigGen as well as sigVer, since sign takes a real message subject to the same
bound. **12 of the 45 official vectors participate in `csim_design`** (`tb_vectors.h`
covers 5 sigVer + 3 deterministic sigGen + 4 hedged sigGen), and the reduced cosim set uses
one fitting case per code path (`sigVer tc12` accept, `tc2` reject; `sigGen tc2`
deterministic, `tc182` hedged - all with non-trivial `ctx`). This is a scope reduction of
what this production build can accept as input, correctly reflecting the 1024-byte bound -
not a bug, and not something to "fix" back to passing all 45 by re-growing the buffer.

If a future deployment genuinely needs to verify longer messages directly, revisit this
number specifically against that requirement rather than reverting to NIST's own
worst-case test length.

**Honesty note on "production":** 1024 is a reasoned default informed by general
automotive/aerospace message-size conventions and FIPS 204's own pre-hash guidance above
- it is not derived from a specific, named target protocol or customer requirement. Treat
it as a documented, justified placeholder, not a value signed off by an actual system
spec. `AXI_DEPTH_MU_ORIG`/`AXI_DEPTH_SIGN_M` (and the other values that must track them,
listed above) are a single point of change if a real target protocol turns out to need
something smaller (e.g. 512 or 256) or larger.

### Known finding: resource utilization on the real target part (`xcku040-sfva784-1-c`)

Synthesizing this design (post-`ctx`/`rnd` fixes, at the 1024-byte message bound above)
against the actual Trenz `xcku040` target - not the upstream default `xcu280` (Alveo
U280), a much larger part - surfaced a resource problem serious enough to record here
even though it isn't something this session finished resolving: **BRAM was over its
1200-block budget, and LUT was at 97% with essentially no margin**, before this
accelerator even has to share the fabric with MicroBlaze V, the AXI interconnect, BRAM
controllers, UART, or - eventually - any reliability/fault-tolerance hardware
(TMR-style redundancy typically costs ~2-3x whatever it's protecting).

#### BRAM: fixed (1205/1200 -> 867/1200, 72% utilization)

Most `hls::stream` depths throughout `k_dsa.cpp` were declared as either a uniform `*2`
margin on top of the real data volume (`dataflow()`'s sign-path streams, e.g.
`depth=paramk*paramn*2` where the real need is `paramk*paramn`), or flat, clearly
not-computed-from-first-principles magic numbers (`k_verify`'s `depth=5000`/`10000`
regardless of what a given stream actually held). Recomputing every such depth against
its real logical size (removing the uniform margin in `dataflow()`; replacing magic
numbers in `k_verify` with `paramk*paramn`/`paraml*paramn`/`paramk*paraml*paramn`/
`paramk*POLYW1_PACKEDBYTES`-style expressions matching what each stream actually
carries) cut BRAM usage by 338 blocks (28%) with **zero change to LUT, FF, DSP, or
timing**, and no correctness regression (confirmed via full `cosim_design` re-run,
`C/RTL co-simulation finished: PASS`). This is a safe, already-applied fix - not a
finding still open.

#### LUT: NOT fixed - two large hardware-duplication clusters identified, totaling ~123K LUT (52% of the design)

Depth pragmas only affect buffer/FIFO sizing; they have nothing to do with LUT
consumption. Digging into the post-synthesis instance-level report (`csynth`'s
`mldsa_accelerator_csynth.rpt` and each submodule's own report) found the real LUT cost
concentrated in two clusters, both the same underlying mechanism: **Vitis HLS gives
every call site of a function inside a `#pragma HLS DATAFLOW` region its own dedicated
hardware instance by default**, so that stages *could* run concurrently for throughput -
regardless of whether the algorithm's own data dependencies actually allow that
concurrency to be used.

1. **`shakeVer` (SHAKE256/Keccak), 6 instances, ~64,052 LUT total:**
   - `k_verify`: `shakeVer` (10,651), `shakeVer_108` (11,339), `shakeVer_116` (10,642) -
     one call site each for computing `tr`, `mu`, and the challenge hash.
   - `dataflow` (sign path): `shake4` (10,914), `shake_key_mu` (9,650), `shake_mu_p`
     (10,856) - structurally the same pattern, three different named functions rather
     than three calls to the same one.
   - In `k_verify`'s case specifically, the three calls form a strict data dependency
     chain (`tr` -> `mu` -> challenge hash - each needs the previous one's output), so
     they can never execute concurrently regardless of hardware sharing: **sharing them
     would very likely cost nothing in latency for a single verify call.**
2. **`nttVer_layerVer`/`invnttVer_layerVer` (NTT butterfly network layers), 104 instances
   combined, ~59,472 LUT total** (`k_verify`: 32 instances / 18,567 LUT; `dataflow`: 72
   instances / 40,905 LUT) - the same cloning mechanism, triggered by `nttVer()`/
   `invnttVer()` being called multiple times (once per polynomial vector needing a
   transform: `s1`, `s2`, `t0`, `z`, `cp`, ... ) with different constant `times`
   arguments, each spawning its own full 8-layer butterfly network rather than reusing
   one. Most of these calls are also sequentially forced by the Fiat-Shamir structure
   (matrix-vector product -> challenge -> response -> norm checks), so - as with
   `shakeVer` - sharing is more likely a genuine free lunch than a real throughput
   trade-off, but this needs case-by-case confirmation, not an assumption.

**Attempted fix, confirmed not to work as a simple pragma:** `#pragma HLS ALLOCATION
function instances=shakeVer limit=1` (correct syntax - `function` immediately after
`ALLOCATION` - the first attempt had this backwards and was silently ignored with a
different warning). Re-synthesizing produced **identical LUT numbers** and this warning:

```
WARNING: [HLS 214-300] Ignoring ALLOCATION pragma, because the corresponding function
is cloned and results in calls to multiple clones [ call, call, call ]
```

Vitis HLS's front-end clones a function into separate specialized copies per call site
*before* `ALLOCATION`'s sharing logic runs, whenever call sites differ in argument
characteristics - here, the three `shakeVer` calls differ in output length (`CRHBYTES`
vs `CTILDEBYTES`), in whether the input length is a compile-time constant or a runtime
variable, and in the declared depth of each call's input stream (`s_pk_1`=200,
`s_mu_mrg`=1408, `s_mubuf`=832). Once cloned, there is no longer "one function, three
calls" left for the pragma to merge - confirmed against AMD's own documented explanation
of this exact warning class (mismatched argument/array-partition characteristics across
call sites defeat allocation-based sharing). The (reverted, not shipped) pragma is left
out of `k_dsa.cpp`; only this documentation and a short code comment remain.

**Second attempt, also confirmed not to work:** normalized all three `shakeVer` call
sites to look identical to the compiler - routed every argument (`outlen`, `inlen`,
`r`, `version`) through a `volatile` local variable at each call site (so no argument
could be seen as a compile-time constant), and gave all three input streams
(`s_pk_1`, `s_mu_mrg`, `s_mubuf`) the same declared depth. Re-synthesized and re-ran
`cosim_design`: **the exact same "Ignoring ALLOCATION pragma... function is cloned"
warning still appeared, and LUT usage went up rather than down** (236,801 -> 240,070,
97% -> 99%) - the `volatile` variables added real logic to force the values to be
treated as non-constant, with no sharing benefit to offset it. Correctness still held
(`cosim_design` still reported `PASS`), so this wasn't a functional regression, but it
was a strictly worse resource trade-off. Reverted in full (all three call sites, the
two stream-depth changes, and the pragma) back to the validated 867 BRAM / 236,801 LUT
/ 97% state.

This is stronger evidence than the first attempt suggested: the cloning is very likely
not really an argument-matching problem at all, but an inherent property of
`#pragma HLS DATAFLOW` itself - each call site probably has to be a distinct,
independently-schedulable node in the dataflow graph, which may be fundamentally
incompatible with `ALLOCATION`-based sharing for repeated calls to the same function
inside a dataflow region, regardless of how identical the arguments are made to look.
**Closing this gap for real would likely need a structural change instead of a
pragma/argument fix** - e.g. moving the repeated calls to a single call site (a small
wrapper invoked once per logical use, outside strict dataflow concurrency), or a
different resource-sharing mechanism entirely - which is a genuine redesign question,
not something to keep iterating on via pragmas. Not attempted further this session;
documented here as a quantified, credible-but-now-doubtful opportunity (~123K LUT, if
both clusters could somehow be shared down to near-single-instance cost) rather than
a completed fix.

**Other large single-instance (non-duplicated) LUT consumers, for completeness** -
these have no "free" sharing win available since there is already only one instance of
each, and are not further investigated here: `make_bufVer`/`make_buf` (`k_verify`
13,186 + `dataflow` 12,353 = 25,539 LUT, ExpandA/rejection-sampling buffer filling),
`challengeVer`/`challengeVer_144` (12,237 + 12,237 = 24,474 LUT, `SampleInBall`
challenge generation).

**Bottom line:** even a fully successful de-duplication of both clusters - optimistic,
unverified - would bring LUT usage down from 97% to roughly 55-60%, which is real
progress but still needs to share the same fabric with MicroBlaze V, the AXI
interconnect, BRAM controllers, and UART, before any reliability/fault-tolerance logic
is added on top. This reinforces, from a resource-budget angle rather than a purely
research-motivated one, the same conclusion the literature review's "Gap 1" already
argued for: **selective, not blanket, hardening of this design is likely the only
approach that fits this specific board**, regardless of how much of the LUT
duplication above eventually gets reclaimed.

#### Documented future avenue (not pursued): sharing sign/verify's internal message streams

`sign_m_in` and `mu_orig_in` already share one physical AXI port (`bundle=gmemm`), since
`kem_cfg` guarantees only one of `k_sign`/`k_verify` ever runs per invocation. Their
*internal* streams don't get the same treatment: `k_verify`'s `s_m`/`s_ctx`/`s_mu_mrg` and
`dataflow()`'s `s_m_sign`/`s_ctx_sign`/`s_mu_mrg_sign` are separately-declared streams in
two different functions, each sized to the same 1024/255/1408 bound - likely duplicated in
hardware even though only one set is ever live at a time. Unlike the `bundle=gmemm` sharing
(a simple, low-risk pragma-level choice), sharing storage here would mean two *structurally
different* functions reusing the same underlying buffer, not repeated calls to one function
- closer in kind to the `shakeVer`/`ALLOCATION` sharing attempts above, which HLS's
DATAFLOW-driven cloning defeated and which made LUT usage worse, not better, on the one
attempt tried. Not investigated further here: real (Vivado-synthesized, not HLS
csynth-estimated) measurements taken before this `k_sign` change showed comfortable margin
against the device budget, so there's no current pressure to chase this, and it carries
the same "might backfire" risk already demonstrated once this session. Those measurements
predate `sign_m_in`/the on-chip sign-side mu derivation, though, so treat them as
directional, not a re-confirmed number for this exact build. Worth revisiting only if a
concrete future need for more headroom arises (e.g. budgeting for TMR-style redundancy).