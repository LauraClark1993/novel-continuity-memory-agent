import pytest

from novel_memory_agent.database import NovelDatabase
from novel_memory_agent.deepseek import DeepSeekError
from novel_memory_agent.evaluation import build_evaluation
from novel_memory_agent.quality_evaluation import _validate_result, summarize_results


def test_empty_project_evaluation(tmp_path) -> None:
    database = NovelDatabase(tmp_path / "evaluation.db")
    novel_id = database.create_novel("测试小说")
    report, metrics = build_evaluation(database, novel_id)
    assert "MVP 效果验证报告" in report
    assert metrics["accepted_generated_chapters"] == 0
    assert metrics["actual_cost_cny"] == 0


def test_quality_result_uses_v2_ten_dimension_score() -> None:
    result = _validate_result(
        {
            "scores": {
                "factual_consistency": 90, "character_consistency": 80,
                "state_consistency": 70, "spatial_consistency": 60,
                "temporal_consistency": 50, "chapter_transition": 40,
                "cross_chapter_causality": 30, "foreshadowing_consistency": 20,
                "outline_boundary": 10, "narrative_pacing": 0,
            },
            "reference_plot_function_score": 85,
        },
        chapter=5,
    )
    assert result["overall_score"] == 45.0
    assert result["reference_plot_function_score"] == 85.0
    assert result["experiment_effect_score"] == pytest.approx(48.636, abs=0.001)


def test_summary_contains_scores_only() -> None:
    result = {
        "overall_score": 4.0,
        "scores": {
            "factual_consistency": 80, "character_consistency": 80,
            "state_consistency": 80, "spatial_consistency": 80,
            "temporal_consistency": 80, "chapter_transition": 80,
            "cross_chapter_causality": 80, "foreshadowing_consistency": 80,
            "outline_boundary": 80, "narrative_pacing": 80,
        },
        "reference_plot_function_score": 75,
        "experiment_effect_score": 79.545,
    }
    summary = summarize_results([result])
    assert summary["overall_score"] == 4.0
    assert summary["reference_plot_function_score"] == 75
    assert summary["experiment_effect_score"] == 79.545
    assert "acceptance_status" not in summary
    assert "severity_counts" not in summary


def test_quality_score_rejects_out_of_range_value() -> None:
    with pytest.raises(DeepSeekError):
        _validate_result(
            {
                "scores": {
                    "factual_consistency": 101, "character_consistency": 80,
                    "state_consistency": 80, "spatial_consistency": 80,
                    "temporal_consistency": 80, "chapter_transition": 80,
                    "cross_chapter_causality": 80, "foreshadowing_consistency": 80,
                    "outline_boundary": 80, "narrative_pacing": 80,
                },
                "reference_plot_function_score": None,
            },
            chapter=5,
        )
