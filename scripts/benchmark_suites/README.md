# Benchmark-suite algorithm support

InferQ supports ingesting benchmark circuits from SupermarQ, MQT Bench, and
QASMBench in addition to its randomly generated circuits.

The source-of-truth inventory is:

- `benchmark_algorithms_full.csv`: suite-specific benchmark entries.
- `benchmark_algorithms_deduplicated.csv`: normalized algorithm families after
  merging equivalent algorithms across suites and problem sizes.

Current counts:

| Inventory | Count |
| --- | ---: |
| Suite-specific entries in `benchmark_algorithms_full.csv` | 109 |
| Deduplicated algorithm families in `benchmark_algorithms_deduplicated.csv` | 85 |

The 109 suite-specific entries consist of 8 SupermarQ entries, 34 MQT Bench
entries, and 67 QASMBench entries. The deduplicated CSV has 85 rows, excluding
the header. In that deduplicated list, 8 families have SupermarQ coverage, 34
have MQT Bench coverage, and 52 have QASMBench coverage; these source-coverage
counts are not additive because some families appear in more than one suite.

Algorithm names marked with `*` are duplicate normalized families. That means
the same algorithm family appears in more than one source suite, or in multiple
problem-size entries inside one source suite. The `Duplicate name` column gives
the normalized family name used by `benchmark_algorithms_deduplicated.csv`.

## Files

| File | Purpose |
| --- | --- |
| `README.md` | Human-readable benchmark inventory, file map, and duplicate notes. |
| `__init__.py` | Package marker for benchmark-suite loader imports. |
| `base.py` | Shared loader abstractions and metadata helpers. |
| `supermarq_loader.py` | SupermarQ benchmark loader. |
| `mqt_bench_loader.py` | MQT Bench benchmark loader. |
| `qasmbench_loader.py` | QASMBench benchmark loader. |
| `benchmark_algorithms_full.csv` | Full suite-specific algorithm list used for ingestion coverage checks. |
| `benchmark_algorithms_deduplicated.csv` | Normalized algorithm-family inventory with source mappings and entry counts. |
| `qasmbench_qasm/MANIFEST.txt` | Vendored QASMBench QASM manifest. |
| `qasmbench_qasm/LICENSE` | License file for vendored QASMBench inputs. |

## Benchmark Algorithms

| Benchmark name | Algorithm | Description | Duplicate name |
| --- | --- | --- | --- |
| `supermarq` | `bit_code` | SupermarQ bit-code error-detection benchmark. | No |
| `supermarq` | `ghz*` | Greenberger-Horne-Zeilinger entangled-state benchmark. | Yes: `ghz` |
| `supermarq` | `ham_sim` | Hamiltonian-simulation benchmark from SupermarQ. | No |
| `supermarq` | `mermin_bell` | Mermin-Bell inequality benchmark from SupermarQ. | No |
| `supermarq` | `phase_code` | SupermarQ phase-code error-detection benchmark. | No |
| `supermarq` | `qaoa_fermionic` | SupermarQ fermionic QAOA workload. | No |
| `supermarq` | `qaoa_vanilla` | SupermarQ vanilla QAOA workload. | No |
| `supermarq` | `vqe_proxy` | SupermarQ proxy workload for VQE-style circuits. | No |
| `mqtbench` | `ae` | Amplitude estimation benchmark for estimating event probabilities. | No |
| `mqtbench` | `bmw_quark_cardinality` | MQT Bench cardinality-estimation workload from the BMW/Quark finance set. | No |
| `mqtbench` | `bmw_quark_copula` | MQT Bench copula-model workload from the BMW/Quark finance set. | No |
| `mqtbench` | `bv*` | Bernstein-Vazirani hidden-string benchmark. | Yes: `bv` |
| `mqtbench` | `cdkm_ripple_carry_adder` | Cuccaro-Draper-Kutin-Moulton ripple-carry adder. | No |
| `mqtbench` | `dj` | Deutsch-Jozsa algorithm benchmark. | No |
| `mqtbench` | `draper_qft_adder` | Draper adder based on the quantum Fourier transform. | No |
| `mqtbench` | `full_adder` | One-bit full-adder arithmetic circuit. | No |
| `mqtbench` | `ghz*` | Greenberger-Horne-Zeilinger entangled-state benchmark. | Yes: `ghz` |
| `mqtbench` | `ghz_dynamic` | Dynamic-circuit GHZ state-preparation benchmark. | No |
| `mqtbench` | `graphstate` | Graph-state preparation benchmark. | No |
| `mqtbench` | `grover*` | Grover search benchmark. | Yes: `grover` |
| `mqtbench` | `half_adder` | One-bit half-adder arithmetic circuit. | No |
| `mqtbench` | `hhl*` | Harrow-Hassidim-Lloyd linear-system solver benchmark. | Yes: `hhl` |
| `mqtbench` | `hrs_cumulative_multiplier` | Haner-Roetteler-Svore cumulative multiplier benchmark. | No |
| `mqtbench` | `modular_adder` | Modular arithmetic adder benchmark. | No |
| `mqtbench` | `multiplier*` | Quantum multiplication arithmetic benchmark. | Yes: `multiplier` |
| `mqtbench` | `qaoa*` | Quantum approximate optimization algorithm benchmark. | Yes: `qaoa` |
| `mqtbench` | `qft*` | Quantum Fourier transform benchmark. | Yes: `qft` |
| `mqtbench` | `qftentangled` | QFT benchmark on an entangled input state. | No |
| `mqtbench` | `qnn` | Quantum neural-network benchmark from MQT Bench. | No |
| `mqtbench` | `qpeexact` | Exact quantum phase-estimation benchmark. | No |
| `mqtbench` | `qpeinexact` | Inexact quantum phase-estimation benchmark. | No |
| `mqtbench` | `qwalk` | Quantum-walk benchmark from MQT Bench. | No |
| `mqtbench` | `randomcircuit` | Random circuit benchmark. | No |
| `mqtbench` | `rg_qft_multiplier` | Ruiz-Garcia/QFT-based multiplier benchmark. | No |
| `mqtbench` | `seven_qubit_steane_code` | Seven-qubit Steane quantum error-correcting code. | No |
| `mqtbench` | `shor*` | Shor factoring benchmark. | Yes: `shor` |
| `mqtbench` | `shors_nine_qubit_code` | Shor nine-qubit error-correcting code benchmark. | No |
| `mqtbench` | `vbe_ripple_carry_adder` | Vedral-Barenco-Ekert ripple-carry adder. | No |
| `mqtbench` | `vqe_real_amp` | VQE benchmark with a RealAmplitudes ansatz. | No |
| `mqtbench` | `vqe_su2` | VQE benchmark with an EfficientSU2 ansatz. | No |
| `mqtbench` | `vqe_two_local` | VQE benchmark with a TwoLocal ansatz. | No |
| `mqtbench` | `wstate*` | W-state preparation benchmark. | Yes: `wstate` |
| `qasmbench` | `adder_n10*` | Quantum adder circuits over multiple QASMBench problem sizes. This entry is the 10-qubit instance. | Yes: `adder` |
| `qasmbench` | `adder_n4*` | Quantum adder circuits over multiple QASMBench problem sizes. This entry is the 4-qubit instance. | Yes: `adder` |
| `qasmbench` | `basis_change_n3` | Small basis-change circuit used to exercise single-qubit rotations. This entry is the 3-qubit instance. | No |
| `qasmbench` | `basis_trotter_n4` | Trotterized basis-evolution circuit. This entry is the 4-qubit instance. | No |
| `qasmbench` | `bb84_n8` | BB84 quantum key-distribution protocol circuit. This entry is the 8-qubit instance. | No |
| `qasmbench` | `bell_n4` | Bell-state preparation and entanglement benchmark. This entry is the 4-qubit instance. | No |
| `qasmbench` | `bigadder_n18` | Large ripple-style arithmetic adder benchmark. This entry is the 18-qubit instance. | No |
| `qasmbench` | `bv_n14*` | Bernstein-Vazirani hidden-string benchmark. This entry is the 14-qubit instance. | Yes: `bv` |
| `qasmbench` | `bv_n19*` | Bernstein-Vazirani hidden-string benchmark. This entry is the 19-qubit instance. | Yes: `bv` |
| `qasmbench` | `bwt_n21` | Burrows-Wheeler-transform inspired QASMBench workload. This entry is the 21-qubit instance. | No |
| `qasmbench` | `cat_state_n22*` | Cat/GHZ-like state-preparation benchmark. This entry is the 22-qubit instance. | Yes: `cat_state` |
| `qasmbench` | `cat_state_n4*` | Cat/GHZ-like state-preparation benchmark. This entry is the 4-qubit instance. | Yes: `cat_state` |
| `qasmbench` | `cc_n12` | Compact control/classical-computation style QASMBench circuit. This entry is the 12-qubit instance. | No |
| `qasmbench` | `deutsch_n2` | Deutsch algorithm benchmark. This entry is the 2-qubit instance. | No |
| `qasmbench` | `dnn_n16*` | Quantum neural-network/deep-neural-network style benchmark. This entry is the 16-qubit instance. | Yes: `dnn` |
| `qasmbench` | `dnn_n2*` | Quantum neural-network/deep-neural-network style benchmark. This entry is the 2-qubit instance. | Yes: `dnn` |
| `qasmbench` | `dnn_n8*` | Quantum neural-network/deep-neural-network style benchmark. This entry is the 8-qubit instance. | Yes: `dnn` |
| `qasmbench` | `error_correctiond3_n5` | Distance-3 quantum error-correction benchmark. This entry is the 5-qubit instance. | No |
| `qasmbench` | `factor247_n15` | Integer factorization instance targeting 247. This entry is the 15-qubit instance. | No |
| `qasmbench` | `fredkin_n3` | Fredkin controlled-swap gate benchmark. This entry is the 3-qubit instance. | No |
| `qasmbench` | `gcm_n13` | Galois/counter-mode style arithmetic benchmark. This entry is the 13-qubit instance. | No |
| `qasmbench` | `ghz_state_n23` | GHZ-state preparation benchmark. This entry is the 23-qubit instance. | No |
| `qasmbench` | `grover_n2*` | Grover search benchmark. This entry is the 2-qubit instance. | Yes: `grover` |
| `qasmbench` | `hhl_n10*` | Harrow-Hassidim-Lloyd linear-system solver benchmark. This entry is the 10-qubit instance. | Yes: `hhl` |
| `qasmbench` | `hhl_n14*` | Harrow-Hassidim-Lloyd linear-system solver benchmark. This entry is the 14-qubit instance. | Yes: `hhl` |
| `qasmbench` | `hhl_n7*` | Harrow-Hassidim-Lloyd linear-system solver benchmark. This entry is the 7-qubit instance. | Yes: `hhl` |
| `qasmbench` | `hs4_n4` | Hidden-shift style four-qubit QASMBench workload. This entry is the 4-qubit instance. | No |
| `qasmbench` | `inverseqft_n4` | Inverse quantum Fourier transform benchmark. This entry is the 4-qubit instance. | No |
| `qasmbench` | `ipea_n2` | Iterative phase-estimation benchmark. This entry is the 2-qubit instance. | No |
| `qasmbench` | `ising_n10*` | Ising-model simulation benchmark. This entry is the 10-qubit instance. | Yes: `ising` |
| `qasmbench` | `ising_n26*` | Ising-model simulation benchmark. This entry is the 26-qubit instance. | Yes: `ising` |
| `qasmbench` | `iswap_n2` | iSWAP gate benchmark. This entry is the 2-qubit instance. | No |
| `qasmbench` | `knn_n25` | Quantum k-nearest-neighbor classification benchmark. This entry is the 25-qubit instance. | No |
| `qasmbench` | `linearsolver_n3` | Small quantum linear-system solver benchmark. This entry is the 3-qubit instance. | No |
| `qasmbench` | `lpn_n5` | Learning-parity-with-noise benchmark. This entry is the 5-qubit instance. | No |
| `qasmbench` | `multiplier_n15*` | Quantum multiplication arithmetic benchmark. This entry is the 15-qubit instance. | Yes: `multiplier` |
| `qasmbench` | `multiply_n13` | QASMBench multiplication circuit. This entry is the 13-qubit instance. | No |
| `qasmbench` | `pea_n5` | Phase-estimation algorithm benchmark. This entry is the 5-qubit instance. | No |
| `qasmbench` | `qaoa_n3*` | Quantum approximate optimization algorithm benchmark. This entry is the 3-qubit instance. | Yes: `qaoa` |
| `qasmbench` | `qaoa_n6*` | Quantum approximate optimization algorithm benchmark. This entry is the 6-qubit instance. | Yes: `qaoa` |
| `qasmbench` | `qec9xz_n17` | Nine-qubit X/Z error-correction benchmark. This entry is the 17-qubit instance. | No |
| `qasmbench` | `qec_en_n5` | Quantum error-correction encoder benchmark. This entry is the 5-qubit instance. | No |
| `qasmbench` | `qec_sm_n5` | Quantum error-correction syndrome-measurement benchmark. This entry is the 5-qubit instance. | No |
| `qasmbench` | `qf21_n15` | Quantum factorization instance for 21. This entry is the 15-qubit instance. | No |
| `qasmbench` | `qft_n18*` | Quantum Fourier transform benchmark. This entry is the 18-qubit instance. | Yes: `qft` |
| `qasmbench` | `qft_n4*` | Quantum Fourier transform benchmark. This entry is the 4-qubit instance. | Yes: `qft` |
| `qasmbench` | `qpe_n9` | Quantum phase-estimation benchmark. This entry is the 9-qubit instance. | No |
| `qasmbench` | `qram_n20` | Quantum random-access-memory benchmark. This entry is the 20-qubit instance. | No |
| `qasmbench` | `qrng_n4` | Quantum random-number generator benchmark. This entry is the 4-qubit instance. | No |
| `qasmbench` | `quantumwalks_n2` | Quantum-walk benchmark. This entry is the 2-qubit instance. | No |
| `qasmbench` | `sat_n11*` | Boolean satisfiability oracle/search benchmark. This entry is the 11-qubit instance. | Yes: `sat` |
| `qasmbench` | `sat_n7*` | Boolean satisfiability oracle/search benchmark. This entry is the 7-qubit instance. | Yes: `sat` |
| `qasmbench` | `seca_n11` | Sequential equivalence checking arithmetic benchmark. This entry is the 11-qubit instance. | No |
| `qasmbench` | `shor_n5*` | Shor factoring benchmark. This entry is the 5-qubit instance. | Yes: `shor` |
| `qasmbench` | `simon_n6` | Simon hidden-period benchmark. This entry is the 6-qubit instance. | No |
| `qasmbench` | `square_root_n18` | Quantum square-root arithmetic benchmark. This entry is the 18-qubit instance. | No |
| `qasmbench` | `swap_test_n25` | Swap-test similarity benchmark. This entry is the 25-qubit instance. | No |
| `qasmbench` | `teleportation_n3` | Quantum teleportation protocol benchmark. This entry is the 3-qubit instance. | No |
| `qasmbench` | `toffoli_n3` | Toffoli gate benchmark. This entry is the 3-qubit instance. | No |
| `qasmbench` | `variational_n4` | Generic variational-circuit benchmark. This entry is the 4-qubit instance. | No |
| `qasmbench` | `vqe_n24*` | Variational quantum eigensolver benchmark. This entry is the 24-qubit instance. | Yes: `vqe` |
| `qasmbench` | `vqe_n4*` | Variational quantum eigensolver benchmark. This entry is the 4-qubit instance. | Yes: `vqe` |
| `qasmbench` | `vqe_uccsd_n4*` | VQE benchmark with a UCCSD ansatz. This entry is the 4-qubit instance. | Yes: `vqe_uccsd` |
| `qasmbench` | `vqe_uccsd_n6*` | VQE benchmark with a UCCSD ansatz. This entry is the 6-qubit instance. | Yes: `vqe_uccsd` |
| `qasmbench` | `vqe_uccsd_n8*` | VQE benchmark with a UCCSD ansatz. This entry is the 8-qubit instance. | Yes: `vqe_uccsd` |
| `qasmbench` | `wstate_n27*` | W-state preparation benchmark. This entry is the 27-qubit instance. | Yes: `wstate` |
| `qasmbench` | `wstate_n3*` | W-state preparation benchmark. This entry is the 3-qubit instance. | Yes: `wstate` |

## Deduplication Notes

The deduplicated total is smaller than the per-suite sum because some algorithm
families appear in multiple suites, such as `ghz`, `grover`, `hhl`, `qaoa`,
`qft`, `shor`, and `wstate`. It also merges same-family QASMBench problem sizes,
such as `adder_n4` with `adder_n10`, `ising_n10` with `ising_n26`, and
`vqe_uccsd_n4` with `vqe_uccsd_n6` and `vqe_uccsd_n8`.
