"""Recompute translation metrics for the committed ``eval_runs/`` artifacts.

The per-sample predictions in ``eval_runs/eval_{val,test}.jsonl`` and the
recorded metrics in ``eval_runs/eval_{val,test}.summary.json`` were produced
by an ad-hoc evaluation script that was never committed. This script restores
reproducibility: given a ``.jsonl`` artifact it recomputes the metrics from
the stored reference/prediction pairs and, when the matching
``.summary.json`` exists, compares each recomputed value against the
recorded one.

Usage (from ``backend/``)::

    uv run python scripts/eval_translation_metrics.py eval_runs/eval_test.jsonl

Dependencies: standard library only, plus ``sacrebleu`` *if it is importable*
from the locked backend environment (it is today, as a transitive dependency
of ``nemo_toolkit[asr]``). No new dependencies are introduced. If sacrebleu
is unavailable the script still runs and computes token-F1 and ROUGE-L in
pure Python; BLEU/chrF are then skipped with a note.

Reproducibility status (verified against the committed summaries):

* ``bleu`` and ``chrf`` — exactly reproduced by sacrebleu defaults
  (``corpus_bleu(hyps, [refs])`` / ``corpus_chrf(hyps, [refs])``). These are
  ENFORCED: a recomputed value differing from the recorded one by more than
  ``1e-3`` makes the script exit nonzero.
* ``rouge_l`` — the recorded values (0.1045 test / 0.1145 val) are exactly
  reproduced by the third-party ``rouge_score`` package with
  ``RougeScorer(["rougeL"], use_stemmer=True)``, i.e. the original script
  used Porter stemming. ``rouge_score`` is NOT a locked backend dependency,
  so this script ships a pure-Python LCS-based ROUGE-L (no stemming) instead,
  which yields 0.0990 (test) / 0.1095 (val). The comparison against the
  summary is therefore INFORMATIONAL for this metric.
* ``token_f1`` — the recorded values (0.1039 test / 0.1162 val) could not be
  matched by any tokenization variant we tried (whitespace split,
  ``\\w+``, edge-punctuation stripping, SQuAD-style normalization, set vs
  multiset overlap, macro vs micro averaging); the original tokenization is
  unrecoverable. This script uses lowercased ``\\w+`` tokens with multiset
  overlap, macro-averaged over samples (empty prediction scores 0), which
  yields 0.1093 (test) / 0.1230 (val). The comparison against the summary is
  INFORMATIONAL for this metric. We document the discrepancy rather than
  tuning the tokenizer to hit the recorded numbers.

``backend/tests/scripts/test_eval_metrics.py`` pins the recomputed values as
the regression baseline going forward.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

#: Metrics whose recomputation is bit-faithful to the recorded summaries.
#: A mismatch beyond TOLERANCE on these is an error (nonzero exit).
ENFORCED_METRICS = frozenset({"bleu", "chrf"})

#: Metrics recorded with a tokenization/stemming we could not recover (see
#: module docstring). Reported against the summary for information only.
INFORMATIONAL_METRICS = frozenset({"token_f1", "rouge_l"})

TOLERANCE = 1e-3

_TOKEN_RE = re.compile(r"\w+")


class EvalRow(TypedDict):
    """One sample of the committed eval artifact (one JSONL line)."""

    sentence_id: str
    reference: str
    gloss: str
    prediction: str
    n_frames: int


def load_rows(path: Path) -> list[EvalRow]:
    """Load reference/prediction rows from a ``.jsonl`` eval artifact."""
    rows: list[EvalRow] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def tokenize(text: str) -> list[str]:
    """Lowercased ``\\w+`` tokens (the documented tokenization, see docstring)."""
    return _TOKEN_RE.findall(text.lower())


def _sentence_token_f1(ref_tokens: list[str], hyp_tokens: list[str]) -> float:
    if not ref_tokens or not hyp_tokens:
        return 0.0
    overlap = sum((Counter(ref_tokens) & Counter(hyp_tokens)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(hyp_tokens)
    recall = overlap / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def token_f1(refs: Sequence[str], hyps: Sequence[str]) -> float:
    """Macro-averaged bag-of-tokens F1 over (reference, prediction) pairs."""
    if len(refs) != len(hyps):
        raise ValueError(f"length mismatch: {len(refs)} refs vs {len(hyps)} hyps")
    if not refs:
        return 0.0
    total = sum(
        _sentence_token_f1(tokenize(ref), tokenize(hyp))
        for ref, hyp in zip(refs, hyps, strict=True)
    )
    return total / len(refs)


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Longest-common-subsequence length, O(len(a) * len(b)) time, O(len(b)) space."""
    if not a or not b:
        return 0
    dp = [0] * (len(b) + 1)
    for token_a in a:
        prev = 0
        for j in range(1, len(b) + 1):
            cur = dp[j]
            dp[j] = prev + 1 if token_a == b[j - 1] else max(dp[j], dp[j - 1])
            prev = cur
    return dp[len(b)]


def _sentence_rouge_l(ref_tokens: list[str], hyp_tokens: list[str]) -> float:
    if not ref_tokens or not hyp_tokens:
        return 0.0
    lcs = _lcs_length(ref_tokens, hyp_tokens)
    if lcs == 0:
        return 0.0
    precision = lcs / len(hyp_tokens)
    recall = lcs / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def rouge_l(refs: Sequence[str], hyps: Sequence[str]) -> float:
    """Macro-averaged LCS-based ROUGE-L F1 (pure Python, no stemming)."""
    if len(refs) != len(hyps):
        raise ValueError(f"length mismatch: {len(refs)} refs vs {len(hyps)} hyps")
    if not refs:
        return 0.0
    total = sum(
        _sentence_rouge_l(tokenize(ref), tokenize(hyp))
        for ref, hyp in zip(refs, hyps, strict=True)
    )
    return total / len(refs)


def sacrebleu_scores(
    refs: Sequence[str], hyps: Sequence[str]
) -> dict[str, float] | None:
    """BLEU and chrF via sacrebleu defaults, or ``None`` if not importable."""
    try:
        import sacrebleu
    except ImportError:
        return None
    hyp_list = list(hyps)
    ref_list = [list(refs)]
    return {
        "bleu": float(sacrebleu.corpus_bleu(hyp_list, ref_list).score),
        "chrf": float(sacrebleu.corpus_chrf(hyp_list, ref_list).score),
    }


def compute_metrics(rows: Sequence[EvalRow]) -> dict[str, float]:
    """All recomputable metrics for the given rows (BLEU/chrF only with sacrebleu)."""
    refs = [row["reference"] for row in rows]
    hyps = [row["prediction"] for row in rows]
    metrics: dict[str, float] = {}
    sb = sacrebleu_scores(refs, hyps)
    if sb is not None:
        metrics.update(sb)
    metrics["token_f1"] = token_f1(refs, hyps)
    metrics["rouge_l"] = rouge_l(refs, hyps)
    metrics["n_samples"] = float(len(rows))
    metrics["n_empty_predictions"] = float(sum(1 for h in hyps if not h.strip()))
    return metrics


def load_summary_metrics(summary_path: Path) -> dict[str, float]:
    """Recorded metrics from a ``.summary.json`` file."""
    with summary_path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    recorded: dict[str, float] = {}
    for key, value in payload.get("metrics", {}).items():
        if isinstance(value, int | float):
            recorded[key] = float(value)
    return recorded


def _emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def _format_row(
    name: str, recomputed: str, recorded: str, delta: str, status: str
) -> str:
    return f"{name:<22}{recomputed:>12}{recorded:>12}{delta:>12}  {status}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recompute translation metrics for an eval_runs .jsonl artifact "
        "and compare against the recorded .summary.json (see module docstring)."
    )
    parser.add_argument("jsonl", type=Path, help="e.g. eval_runs/eval_test.jsonl")
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="summary JSON to compare against (default: <jsonl stem>.summary.json)",
    )
    args = parser.parse_args(argv)

    jsonl_path: Path = args.jsonl
    if not jsonl_path.is_file():
        _emit(f"error: no such file: {jsonl_path}")
        return 2
    summary_path: Path = args.summary or jsonl_path.with_name(
        jsonl_path.stem + ".summary.json"
    )

    rows = load_rows(jsonl_path)
    metrics = compute_metrics(rows)
    if "bleu" not in metrics:
        _emit("note: sacrebleu not importable; BLEU/chrF skipped.")

    recorded = load_summary_metrics(summary_path) if summary_path.is_file() else {}
    if not recorded:
        _emit(f"note: no summary found at {summary_path}; nothing to compare against.")

    _emit(f"{jsonl_path} ({len(rows)} rows)")
    _emit(_format_row("metric", "recomputed", "recorded", "delta", "status"))
    failures = 0
    for name in (
        "bleu",
        "chrf",
        "token_f1",
        "rouge_l",
        "n_samples",
        "n_empty_predictions",
    ):
        if name not in metrics:
            continue
        value = metrics[name]
        if name not in recorded:
            _emit(_format_row(name, f"{value:.4f}", "-", "-", "no recorded value"))
            continue
        delta = value - recorded[name]
        within = abs(delta) <= TOLERANCE
        if name in ENFORCED_METRICS:
            status = (
                "OK (enforced)" if within else f"FAIL (enforced, |delta| > {TOLERANCE})"
            )
            if not within:
                failures += 1
        elif name in INFORMATIONAL_METRICS and not within:
            status = "INFO: known tokenization divergence (see module docstring)"
        else:
            status = "OK"
        _emit(
            _format_row(
                name, f"{value:.4f}", f"{recorded[name]:.4f}", f"{delta:+.4f}", status
            )
        )

    if failures:
        _emit(f"{failures} enforced metric(s) outside tolerance {TOLERANCE}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
