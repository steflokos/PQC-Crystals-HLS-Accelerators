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

Both changes were validated via HLS C-simulation (`csim_design`) against the official
[NIST ACVP-Server](https://github.com/usnistgov/ACVP-Server) ML-DSA-44 KAT vectors
(`gen-val/json-files/ML-DSA-{sigGen,sigVer}-FIPS204`): 45/45 cases passing, covering
verify with non-trivial `context` values (including negative/malformed signatures,
correctly rejected), and sign with both `rnd = 0` and real hedged `rnd` values, each
checked for a byte-exact signature match against the NIST-published expected output.