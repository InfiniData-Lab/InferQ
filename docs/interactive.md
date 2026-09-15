# Interactive Mode

Interactive mode is a guided `main.py` entry point for building a circuit from
specific generator templates. It is useful when you want a reproducible
composition instead of letting the probability-based generator choose every
part.

```bash
cd InferQ
python main.py interactive
```

To stop after building the composed circuit, use:

```bash
python main.py interactive --generate-only
```

## What It Does

Interactive mode creates the same `CircuitMerger` and `BaseParams` objects used
by the production pipeline, but it asks you which generator templates to compose.
The prompts enumerate available templates from `generators/`, then accept:

- One-based indexes, such as `1,4,9`
- Inclusive index ranges, such as `2-5`
- Generator class names, such as `GHZ,QFTGenerator`

After each selected template, InferQ previews that template's generated default
parameters and lets you override them. Overrides can be written either as
`key=value` pairs or as a Python/JSON dictionary.

```text
num_qubits=4,inverse=true,do_swaps=false
{"num_qubits": 5, "do_swaps": false}
```

## Deterministic Composition Parts

Interactive mode is intended to deterministically create parts of compositions.
When you explicitly select templates and provide parameter overrides, the ordered
composition is fixed: each step names a generator and the exact parameter set
used to produce that part of the circuit.

That explicit composition path is implemented through
`CircuitMerger.generate_composed_circuit()`. Each selected item becomes a
`CompositionStep`, and the merger builds the final circuit from those steps in
the order you provided. This is different from pressing Enter at the composition
prompt, which falls back to the existing probability-based hierarchical
generator path.

## Pipeline Behavior

After the interactive circuit is built, InferQ prints the circuit size summary.
Unless `--generate-only` was used, it then asks whether to continue with the
normal processing path:

- Feature extraction
- Simulation through the configured Qiskit and InfiniQuantumSim settings
- Local storage
- Optional cloud upload, when enabled in configuration

The same configuration sources apply as in other modes. Circuit bounds,
measurement behavior, seeds, simulator settings, storage behavior, and cloud
settings are read from `config.py` through the existing helper functions.

## Example Session

```text
Composition (indexes/names/ranges, comma-separated; Enter for random): GHZ,QFTGenerator

Step 1: GHZ
Default parameters:
{
  "num_qubits": 3
}
Overrides as key=value pairs or a Python/JSON dict (Enter to keep defaults): num_qubits=4

Step 2: QFTGenerator
Default parameters:
{
  "num_qubits": 4,
  "inverse": false,
  "do_swaps": true,
  "entangled": false
}
Overrides as key=value pairs or a Python/JSON dict (Enter to keep defaults): do_swaps=false
```

This creates a fixed two-part composition: a GHZ circuit with four qubits,
followed by a QFT generator step with swaps disabled.

## Related Code

- `main.py`: dispatches `python main.py interactive` and controls whether the
  built circuit continues into the extraction/simulation/storage pipeline.
- `generators/interactive_composer.py`: parses selections and parameter
  overrides, prompts for composition steps, and falls back to random generation
  when no explicit composition is entered.
- `generators/circuit_merger.py`: resolves generator names, normalizes
  composition steps, generates each selected part, and composes the final
  circuit.
