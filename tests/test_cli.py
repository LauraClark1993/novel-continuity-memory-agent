from novel_memory_agent.cli import build_parser


def test_test_api_command_defaults_to_configured_model() -> None:
    args = build_parser().parse_args(["test-api"])
    assert args.command == "test-api"
    assert args.model is None
    assert args.visible_input is False


def test_test_api_can_enable_visible_input() -> None:
    args = build_parser().parse_args(["test-api", "--visible-input"])
    assert args.visible_input is True


def test_generate_command_parses_outline_and_target() -> None:
    args = build_parser().parse_args(
        ["generate", "3", "--outline", "5", "--target-chars", "2800"]
    )
    assert args.novel_id == 3
    assert args.outline == 5
    assert args.target_chars == 2800


def test_preview_can_use_isolated_output_directory() -> None:
    args = build_parser().parse_args(
        ["preview", "1", "--outline", "5", "--output", "outputs_v2"]
    )
    assert args.output.name == "outputs_v2"


def test_memory_status_command() -> None:
    args = build_parser().parse_args(["memory-status", "9", "confirmed"])
    assert args.memory_id == 9
    assert args.status == "confirmed"


def test_review_memories_command() -> None:
    args = build_parser().parse_args(["review-memories", "1"])
    assert args.novel_id == 1


def test_state_import_command() -> None:
    args = build_parser().parse_args(["state-import", "1", "--file", "state.json"])
    assert args.novel_id == 1
    assert args.file.name == "state.json"


def test_state_show_section_command() -> None:
    args = build_parser().parse_args(["state-show", "1", "--section", "locations"])
    assert args.section == "locations"


def test_state_init_command() -> None:
    args = build_parser().parse_args(["state-init", "1", "--through-chapter", "4"])
    assert args.novel_id == 1
    assert args.through_chapter == 4


def test_clone_v2_database_command() -> None:
    args = build_parser().parse_args(
        [
            "clone-v2-db",
            "1",
            "--through-chapter",
            "4",
            "--output-db",
            "data/v2.db",
        ]
    )
    assert args.through_chapter == 4
    assert args.output_db.name == "v2.db"


def test_run_book_command_defaults() -> None:
    args = build_parser().parse_args(["run-book", "1", "--end", "65"])
    assert args.start == 5
    assert args.end == 65
    assert args.target_chars == 3000
    assert args.max_cost == 200.0


def test_budget_set_command() -> None:
    args = build_parser().parse_args(["budget-set", "1", "300"])
    assert args.amount == 300
