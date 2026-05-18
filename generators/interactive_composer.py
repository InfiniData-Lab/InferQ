"""Interactive generator-template composition for InferQ."""

from __future__ import annotations

import ast
import json
from typing import Any, Callable, Iterable

from qiskit import QuantumCircuit

from generators.circuit_merger import CircuitMerger, CompositionStep


PromptFn = Callable[[str], str]


def pick_composition_parts(
    selection: str,
    available_names: Iterable[str],
) -> list[str]:
    """
    Pick generator names from a user-facing enumeration.

    The selector accepts one-based indexes, class names, and inclusive index
    ranges. Examples: "1,4,9", "QFTGenerator, QPE", "2-5".
    """
    names = list(available_names)
    name_lookup = {name.lower(): name for name in names}
    picked: list[str] = []

    for token in _split_top_level(selection):
        token = token.strip()
        if not token:
            continue

        if "-" in token and _looks_like_range(token):
            start_text, end_text = token.split("-", 1)
            start = int(start_text) - 1
            end = int(end_text) - 1
            if start > end:
                start, end = end, start
            for index in range(start, end + 1):
                picked.append(_name_at_index(names, index))
            continue

        if token.isdigit():
            picked.append(_name_at_index(names, int(token) - 1))
            continue

        match = name_lookup.get(token.lower())
        if match is None:
            raise ValueError(f"Unknown generator selection: {token}")
        picked.append(match)

    return picked


def prompt_for_composition(
    merger: CircuitMerger,
    *,
    prompt: PromptFn = input,
) -> list[CompositionStep] | None:
    """
    Prompt the user for an explicit composition.

    Returns None when the user chooses the existing probability-based random
    generator path.
    """
    names = merger.list_generator_names()
    print("\nAvailable generator templates:")
    for i, name in enumerate(names, start=1):
        print(f"  {i:2d}. {name}")

    raw_selection = prompt(
        "\nComposition (indexes/names/ranges, comma-separated; Enter for random): "
    ).strip()
    if not raw_selection:
        return None

    selected_names = pick_composition_parts(raw_selection, names)
    if not selected_names:
        raise ValueError("No generator templates selected")

    steps: list[CompositionStep] = []
    for position, name in enumerate(selected_names, start=1):
        generator = merger.get_generator(name)
        default_parameters = merger.get_default_parameters(generator)
        print(f"\nStep {position}: {name}")
        print("Default parameters:")
        print(_format_parameters(default_parameters))

        raw_overrides = prompt(
            "Overrides as key=value pairs or a Python/JSON dict (Enter to keep defaults): "
        ).strip()
        parameters = default_parameters
        if raw_overrides:
            overrides = parse_parameter_overrides(raw_overrides)
            unknown = set(overrides) - set(default_parameters)
            if unknown:
                allowed = ", ".join(default_parameters)
                raise ValueError(
                    f"Unknown parameter(s) for {name}: {', '.join(sorted(unknown))}. "
                    f"Allowed: {allowed}"
                )
            parameters = {**default_parameters, **overrides}

        steps.append(CompositionStep(generator_name=name, parameters=parameters))

    return steps


def generate_interactive_circuit(
    merger: CircuitMerger,
    *,
    stopping_probability: float,
    max_generators: int,
    prompt: PromptFn = input,
) -> QuantumCircuit:
    """Build a circuit through prompts, falling back to random generation."""
    composition = prompt_for_composition(merger, prompt=prompt)
    if composition is None:
        return merger.generate_hierarchical_circuit(
            stopping_probability=stopping_probability,
            max_generators=max_generators,
        )

    return merger.generate_composed_circuit(composition)


def parse_parameter_overrides(raw: str) -> dict[str, Any]:
    """
    Parse interactive parameter overrides.

    Supported forms:
    - {"num_qubits": 4, "inverse": true}
    - {'num_qubits': 4, 'inverse': True}
    - num_qubits=4,inverse=true
    """
    raw = raw.strip()
    if not raw:
        return {}

    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = ast.literal_eval(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Parameter override literal must be a dict")
        return parsed

    overrides: dict[str, Any] = {}
    for part in _split_top_level(raw):
        if "=" not in part:
            raise ValueError(f"Expected key=value override, got: {part}")
        key, value = part.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Missing parameter name in override: {part}")
        overrides[key] = _parse_value(value.strip())
    return overrides


def prompt_yes_no(
    question: str,
    *,
    default: bool,
    prompt: PromptFn = input,
) -> bool:
    """Prompt for a yes/no answer."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = prompt(question + suffix).strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def _parse_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"none", "null"}:
        return None
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw


def _split_top_level(raw: str) -> list[str]:
    """Split on commas while preserving nested lists/dicts/tuples and strings."""
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False

    for i, char in enumerate(raw):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in {"'", '"'}:
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(raw[start:i])
            start = i + 1

    parts.append(raw[start:])
    return parts


def _looks_like_range(token: str) -> bool:
    left, right = token.split("-", 1)
    return left.strip().isdigit() and right.strip().isdigit()


def _name_at_index(names: list[str], index: int) -> str:
    try:
        return names[index]
    except IndexError as exc:
        raise ValueError(f"Generator index out of range: {index + 1}") from exc


def _format_parameters(parameters: dict[str, Any]) -> str:
    try:
        return json.dumps(parameters, indent=2, default=str)
    except TypeError:
        return "\n".join(f"  {key}: {value!r}" for key, value in parameters.items())
