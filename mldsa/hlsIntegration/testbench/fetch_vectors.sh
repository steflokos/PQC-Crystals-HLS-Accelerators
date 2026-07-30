#!/usr/bin/env bash
# Downloads the official NIST ACVP-Server ML-DSA KAT vectors used by gen_vectors.py.
# Source: https://github.com/usnistgov/ACVP-Server, gen-val/json-files/
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p vectors
for dir in "ML-DSA-keyGen-FIPS204" "ML-DSA-sigGen-FIPS204" "ML-DSA-sigVer-FIPS204"; do
    mkdir -p "vectors/$dir"
    for f in "prompt.json" "expectedResults.json" "internalProjection.json" "registration.json"; do
        echo "Fetching $dir/$f ..."
        curl -sL "https://raw.githubusercontent.com/usnistgov/ACVP-Server/master/gen-val/json-files/$dir/$f" \
            -o "vectors/$dir/$f"
    done
done
echo "Done. Run 'python3 gen_vectors.py' next to generate tb_vectors.h."
