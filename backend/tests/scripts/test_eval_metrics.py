"""Regression tests for ``scripts/eval_translation_metrics.py``.

These tests recompute translation metrics from the committed
``eval_runs/eval_{val,test}.jsonl`` artifacts and pin the results.

Reproducibility status (the honest version — see also the script docstring):

* ``bleu`` / ``chrf`` are asserted against the committed ``.summary.json``
  values within 1e-3 — sacrebleu defaults reproduce them exactly.
* ``token_f1`` / ``rouge_l`` do NOT match the committed summaries: the
  original (never-committed) eval script used a tokenization we could not
  recover. Recorded ``rouge_l`` is exactly reproduced by the ``rouge_score``
  package with Porter stemming (not a locked dependency); recorded
  ``token_f1`` matched none of the variants tried. Rather than fudging the
  tokenizer to hit the recorded numbers, these tests pin the values
  recomputed by our documented implementation (lowercased ``\\w+`` tokens)
  as the regression baseline:

  ===========  ==========  ========  ==========  ========
  metric       test (ours) recorded  val (ours)  recorded
  ===========  ==========  ========  ==========  ========
  token_f1     0.109307    0.1039    0.122985    0.1162
  rouge_l      0.098986    0.1045    0.109518    0.1145
  ===========  ==========  ========  ==========  ========
"""

from pathlib import Path

import pytest

from scripts.eval_translation_metrics import (
    load_rows,
    load_summary_metrics,
    rouge_l,
    sacrebleu_scores,
    token_f1,
)

EVAL_RUNS_DIR = Path(__file__).resolve().parents[2] / "eval_runs"

# Regression baselines recomputed with the documented tokenization
# (lowercased \w+ tokens; multiset overlap for F1, LCS for ROUGE-L).
PINNED_RECOMPUTED = {
    "test": {"token_f1": 0.109307, "rouge_l": 0.098986},
    "val": {"token_f1": 0.122985, "rouge_l": 0.109518},
}

TOLERANCE = 1e-3

needs_artifacts = pytest.mark.skipif(
    not (EVAL_RUNS_DIR / "eval_test.jsonl").is_file(),
    reason="committed eval_runs artifacts not present",
)


# --- Synthetic unit cases -------------------------------------------------


def test_token_f1_perfect_match() -> None:
    assert token_f1(["The cat sat."], ["the cat sat"]) == pytest.approx(1.0)


def test_token_f1_disjoint() -> None:
    assert token_f1(["alpha beta gamma"], ["delta epsilon"]) == 0.0


def test_token_f1_partial_overlap() -> None:
    # 2 of 4 tokens overlap on both sides -> precision = recall = F1 = 0.5
    assert token_f1(["a b c d"], ["a b x y"]) == pytest.approx(0.5)


def test_rouge_l_perfect_match() -> None:
    assert rouge_l(["The cat sat."], ["the cat sat"]) == pytest.approx(1.0)


def test_rouge_l_disjoint() -> None:
    assert rouge_l(["alpha beta gamma"], ["delta epsilon"]) == 0.0


def test_rouge_l_is_order_sensitive() -> None:
    # Same bag of tokens, reversed order: LCS = 1 -> F1 = 1/3 (token_f1 = 1).
    assert rouge_l(["a b c"], ["c b a"]) == pytest.approx(1 / 3)
    assert token_f1(["a b c"], ["c b a"]) == pytest.approx(1.0)


# --- Committed artifacts --------------------------------------------------


@needs_artifacts
@pytest.mark.parametrize("split", ["test", "val"])
def test_recomputed_metrics_on_committed_artifacts(split: str) -> None:
    rows = load_rows(EVAL_RUNS_DIR / f"eval_{split}.jsonl")
    recorded = load_summary_metrics(EVAL_RUNS_DIR / f"eval_{split}.summary.json")
    refs = [row["reference"] for row in rows]
    hyps = [row["prediction"] for row in rows]

    # Sample counts must agree with the summary exactly.
    assert len(rows) == int(recorded["n_samples"])
    n_empty = sum(1 for h in hyps if not h.strip())
    assert n_empty == int(recorded["n_empty_predictions"])

    # token_f1 / rouge_l: pinned against OUR recomputation (regression
    # baseline), not the summary — the original tokenization is
    # unrecoverable; see module docstring for the recorded values.
    assert token_f1(refs, hyps) == pytest.approx(
        PINNED_RECOMPUTED[split]["token_f1"], abs=TOLERANCE
    )
    assert rouge_l(refs, hyps) == pytest.approx(
        PINNED_RECOMPUTED[split]["rouge_l"], abs=TOLERANCE
    )


@needs_artifacts
@pytest.mark.parametrize("split", ["test", "val"])
def test_bleu_chrf_match_committed_summaries(split: str) -> None:
    rows = load_rows(EVAL_RUNS_DIR / f"eval_{split}.jsonl")
    refs = [row["reference"] for row in rows]
    hyps = [row["prediction"] for row in rows]
    scores = sacrebleu_scores(refs, hyps)
    if scores is None:
        pytest.skip("sacrebleu not importable in this environment")
    recorded = load_summary_metrics(EVAL_RUNS_DIR / f"eval_{split}.summary.json")
    assert scores["bleu"] == pytest.approx(recorded["bleu"], abs=TOLERANCE)
    assert scores["chrf"] == pytest.approx(recorded["chrf"], abs=TOLERANCE)
