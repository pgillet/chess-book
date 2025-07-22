# Build the Database

First, you need to analyze your large PGN file and create the database. This only needs to be done once (or whenever you want to refresh the analysis).

```shell
python select_top_games.py build <input_pgn_file> <database_file>
```

# This will read games.pgn, analyze them, and create analysis.db
python select_top_games.py build games-full.txt analysis.db

This process will take a while as it analyzes every game.

# Export Top Games

Once the database is built, you can run fast queries to export different selections of games.

```shell
python select_top_games.py export <database_file> <output_pgn_file> -n <number> --sort_by <criteria>
```


## Example 1: Get the top 20 best quality games
    
```shell
python select_top_games.py export analysis.db top_20_quality.pgn -n 20 --sort_by quality_score:desc
```


## Example 2: Get the 10 most recent checkmate games

```shell
python select_top_games.py export analysis.db top_10_recent_mates.pgn -n 10 --sort_by game_datetime:desc
```

## Example 3: Get the 15 lowest CPL games, sorted by date

```shell
python select_top_games.py export analysis.db top_15_low_cpl.pgn -n 15 --sort_by avg_cpl:asc game_datetime:asc
```