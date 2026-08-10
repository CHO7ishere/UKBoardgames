from pathlib import Path

from sources.bgg import filter_base_games, load_bg_ranks

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_bg_ranks_parses_all_rows():
    games = load_bg_ranks(FIXTURES / "bg_ranks_sample.csv")
    assert len(games) == 7
    names = {g.name for g in games}
    assert "Spirit Island" in names
    assert "Brass: Birmingham" in names


def test_load_bg_ranks_handles_not_ranked_string():
    games = load_bg_ranks(FIXTURES / "bg_ranks_sample.csv")
    manipulate = next(g for g in games if g.name == "Manipulate")
    assert manipulate.rank is None  # "Not Ranked" -> None, not a crash


def test_load_bg_ranks_parses_types_correctly():
    games = load_bg_ranks(FIXTURES / "bg_ranks_sample.csv")
    spirit_island = next(g for g in games if g.name == "Spirit Island")
    assert spirit_island.id == 1
    assert spirit_island.year == 2017
    assert spirit_island.rank == 17
    assert spirit_island.average == 8.4
    assert spirit_island.usersrated == 60000
    assert spirit_island.is_expansion is False


def test_load_bg_ranks_flags_expansion():
    games = load_bg_ranks(FIXTURES / "bg_ranks_sample.csv")
    branch_claw = next(g for g in games if "Branch" in g.name)
    assert branch_claw.is_expansion is True


def test_filter_base_games_drops_expansions_by_default():
    games = load_bg_ranks(FIXTURES / "bg_ranks_sample.csv")
    base = filter_base_games(games)
    assert len(base) == 6
    assert all(not g.is_expansion for g in base)


def test_filter_base_games_keeps_expansions_when_included():
    games = load_bg_ranks(FIXTURES / "bg_ranks_sample.csv")
    all_games = filter_base_games(games, include_expansions=True)
    assert len(all_games) == 7
