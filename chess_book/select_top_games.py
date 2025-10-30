import argparse
import chess.pgn
import chess.engine
import sys
import sqlite3
from datetime import datetime
import os
import math
import statistics
from collections import defaultdict

# --- CONFIGURATION ---
ENGINE_PATH = "/opt/homebrew/bin/stockfish"

# --- DATABASE SCHEMA ---
DB_SCHEMA = {
    "Link": "TEXT PRIMARY KEY", "Event": "TEXT", "Site": "TEXT", "Date": "TEXT",
    "Round": "TEXT", "White": "TEXT", "Black": "TEXT", "Result": "TEXT",
    "WhiteElo": "INTEGER", "BlackElo": "INTEGER", "TimeControl": "TEXT",
    "Termination": "TEXT", "game_datetime": "TIMESTAMP", "winner": "TEXT",
    "num_moves": "INTEGER",
    "white_cpl": "REAL", "black_cpl": "REAL", # Ensure these are present
    "avg_cpl": "REAL", "cpl_std_dev": "REAL",
    "blunders": "INTEGER", "mistakes": "INTEGER", "quality_score": "REAL",
    "raw_pgn": "TEXT"
}


# --- DATABASE FUNCTIONS ---

def create_connection(db_file):
    """Create a database connection to the SQLite database specified by db_file"""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
    except sqlite3.Error as e:
        print(e)
    return conn


def create_table(conn):
    """Create the games table using the DB_SCHEMA."""
    columns = ", ".join([f'"{col_name}" {col_type}' for col_name, col_type in DB_SCHEMA.items()])
    sql_create_table = f"CREATE TABLE IF NOT EXISTS games ({columns});"
    try:
        c = conn.cursor()
        c.execute(sql_create_table)
    except sqlite3.Error as e:
        print(e)


def insert_game_data(conn, game_data):
    """Insert a new game into the games table."""
    columns = ', '.join(game_data.keys())
    placeholders = ', '.join(['?' for _ in game_data])
    sql = f'INSERT OR REPLACE INTO games ({columns}) VALUES ({placeholders})'
    cur = conn.cursor()
    cur.execute(sql, list(game_data.values()))
    conn.commit()
    return cur.lastrowid


# --- ANALYSIS FUNCTIONS ---

def analyze_game(game, engine, username):
    """Analyzes a single game to extract metrics for both players."""
    analysis_data = {}
    white_cpls = []
    black_cpls = []

    board = game.board()
    moves = list(game.mainline_moves())

    if not moves:
        return None

    for move in moves:
        is_white_move = board.turn == chess.WHITE
        info = engine.analyse(board, chess.engine.Limit(depth=15))
        best_move_score = info.get("score").white()

        board.push(move)

        info_after = engine.analyse(board, chess.engine.Limit(depth=15))
        actual_move_score = info_after.get("score").white()

        if not best_move_score.is_mate() and not actual_move_score.is_mate():
            # CPL is the absolute difference in evaluation
            cpl = abs(best_move_score.score() - actual_move_score.score())
            if is_white_move:
                white_cpls.append(cpl)
            else:
                black_cpls.append(cpl)

    all_cpls = white_cpls + black_cpls
    if not all_cpls:
        return None

    analysis_data['num_moves'] = len(moves)
    analysis_data['white_cpl'] = statistics.mean(white_cpls) if white_cpls else 0
    analysis_data['black_cpl'] = statistics.mean(black_cpls) if black_cpls else 0
    analysis_data['avg_cpl'] = statistics.mean(all_cpls)
    analysis_data['cpl_std_dev'] = statistics.stdev(all_cpls) if len(all_cpls) > 1 else 0
    analysis_data['blunders'] = sum(1 for cpl in all_cpls if cpl >= 200)
    analysis_data['mistakes'] = sum(1 for cpl in all_cpls if 100 <= cpl < 200)

    return analysis_data


def calculate_comparative_score(metrics, stats):
    """
    Calculates a sophisticated, comparative quality score, rewarding balanced, high-precision games.
    """

    def get_z_score(value, mean, std_dev):
        if std_dev == 0: return 0
        return (value - mean) / std_dev

    # Normalize metrics for both players
    white_cpl_z = get_z_score(metrics['white_cpl'], stats['mean_white_cpl'], stats['std_dev_white_cpl'])
    black_cpl_z = get_z_score(metrics['black_cpl'], stats['mean_black_cpl'], stats['std_dev_black_cpl'])
    blunders_z = get_z_score(metrics['blunders'], stats['mean_blunders'], stats['std_dev_blunders'])
    mistakes_z = get_z_score(metrics['mistakes'], stats['mean_mistakes'], stats['std_dev_mistakes'])
    cpl_std_dev_z = get_z_score(metrics['cpl_std_dev'], stats['mean_cpl_std_dev'], stats['std_dev_cpl_std_dev'])

    # --- NEW: Balance Score ---
    # This score rewards games where BOTH players had a low CPL.
    # It penalizes based on the higher (worse) of the two player CPL z-scores.
    balance_score = math.exp(-max(0, white_cpl_z, black_cpl_z))

    # Non-Linear Scaling for other metrics
    blunder_penalty = math.exp(-max(0, blunders_z))
    mistake_penalty = math.exp(-max(0, mistakes_z))
    consistency_score = math.exp(-max(0, cpl_std_dev_z))

    # Weighted Aggregation with the new balance_score
    weights = {'balance': 0.5, 'blunders': 0.2, 'mistakes': 0.1, 'consistency': 0.2}

    quality_score = (
            balance_score ** weights['balance'] *
            blunder_penalty ** weights['blunders'] *
            mistake_penalty ** weights['mistakes'] *
            consistency_score ** weights['consistency']
    )

    # Contextual Adjustments for game length and result
    num_moves = metrics['num_moves']
    midpoint = 25
    k = 0.2
    length_modifier = (1 / (1 + math.exp(-k * (num_moves - midpoint)))) - 0.5
    quality_score += length_modifier * 0.4

    if metrics['winner'] == metrics['username']:
        quality_score += 0.1
        if "checkmate" in metrics.get("Termination", ""):
            quality_score += 0.1

    return min(1.0, max(0.0, quality_score)) * 100


# --- MAIN SCRIPT FUNCTIONS ---

def build_database(input_pgn, db_file, group_by_time_control=False):
    """
    Builds the database in two passes to calculate comparative scores.
    """
    if os.path.exists(db_file):
        os.remove(db_file)

    conn = create_connection(db_file)
    create_table(conn)

    engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)

    username = None
    game_count = 0

    print("--- PASS 1: Analyzing games and collecting raw metrics ---")
    with open(input_pgn) as pgn:
        while True:
            game = chess.pgn.read_game(pgn)
            if game is None: break
            game_count += 1
            if username is None: username = game.headers.get("White")
            print(f"Analyzing game {game_count}...")

            analysis_metrics = analyze_game(game, engine, username)
            if not analysis_metrics: continue

            # --- CORRECTED LOGIC ---
            # This now filters the game headers to only include keys
            # that are defined in our DB_SCHEMA, preventing errors.
            game_data = {}
            for key in DB_SCHEMA.keys():
                if key in game.headers:
                    game_data[key] = game.headers[key]
                elif key in analysis_metrics:
                    game_data[key] = analysis_metrics[key]

            game_data["raw_pgn"] = str(game)
            # Ensure integer fields are correctly typed
            for key in ["WhiteElo", "BlackElo"]:
                if key in game_data and game_data[key] != "?":
                    game_data[key] = int(game_data[key])
                else:
                    game_data[key] = 0

            insert_game_data(conn, game_data)

    print(f"\n--- PASS 2: Calculating comparative quality scores ---")

    cur = conn.cursor()
    cur.execute(
        "SELECT Link, white_cpl, black_cpl, blunders, mistakes, cpl_std_dev, num_moves, White, Black, Result, Termination, TimeControl FROM games")
    all_games_data = cur.fetchall()

    if not all_games_data:
        print("No games were analyzed. Exiting.")
        return

    groups = defaultdict(list)
    for row in all_games_data:
        key = row[11] if group_by_time_control else 'all'
        groups[key].append(row)

    for group_key, group_games in groups.items():
        print(f"Calculating scores for group: '{group_key}' ({len(group_games)} games)")

        stats = {
            'mean_white_cpl': statistics.mean([g[1] for g in group_games]),
            'std_dev_white_cpl': statistics.stdev([g[1] for g in group_games]) if len(group_games) > 1 else 0,
            'mean_black_cpl': statistics.mean([g[2] for g in group_games]),
            'std_dev_black_cpl': statistics.stdev([g[2] for g in group_games]) if len(group_games) > 1 else 0,
            'mean_blunders': statistics.mean([g[3] for g in group_games]),
            'std_dev_blunders': statistics.stdev([g[3] for g in group_games]) if len(group_games) > 1 else 0,
            'mean_mistakes': statistics.mean([g[4] for g in group_games]),
            'std_dev_mistakes': statistics.stdev([g[4] for g in group_games]) if len(group_games) > 1 else 0,
            'mean_cpl_std_dev': statistics.mean([g[5] for g in group_games]),
            'std_dev_cpl_std_dev': statistics.stdev([g[5] for g in group_games]) if len(group_games) > 1 else 0,
        }

        for game_data in group_games:
            link, white_cpl, black_cpl, blunders, mistakes, cpl_std_dev, num_moves, white, black, result, termination, _ = game_data

            winner = ""
            if result == "1-0":
                winner = white
            elif result == "0-1":
                winner = black

            metrics = {
                'white_cpl': white_cpl, 'black_cpl': black_cpl, 'blunders': blunders,
                'mistakes': mistakes, 'cpl_std_dev': cpl_std_dev, 'num_moves': num_moves,
                'winner': winner, 'username': username, 'Termination': termination
            }

            score = calculate_comparative_score(metrics, stats)
            cur.execute("UPDATE games SET quality_score = ? WHERE Link = ?", (score, link))

    conn.commit()
    conn.close()
    engine.quit()
    print(f"\n✅ Database '{db_file}' built and scored successfully.")


def export_top_games(db_file, output_pgn, top_n, sort_by, min_score, max_score):
    """Exports the top N games based on the selected sorting criteria."""
    conn = create_connection(db_file)
    cur = conn.cursor()

    order_clauses = []
    for s in sort_by:
        parts = s.split(':')
        col = parts[0]
        direction = parts[1].upper() if len(parts) > 1 and parts[1].lower() in ['asc', 'desc'] else 'DESC'
        order_clauses.append(f"{col} {direction}")

    query = f"SELECT raw_pgn FROM games"

    where_clauses = []
    params = []
    if min_score is not None:
        where_clauses.append("quality_score >= ?")
        params.append(min_score)
    if max_score is not None:
        where_clauses.append("quality_score <= ?")
        params.append(max_score)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    query += f" ORDER BY {', '.join(order_clauses)} LIMIT ?"
    params.append(top_n)

    cur.execute(query, params)

    rows = cur.fetchall()

    with open(output_pgn, 'w') as f:
        for row in rows:
            f.write(row[0] + "\n\n")

    conn.close()
    print(f"✅ Exported {len(rows)} games to '{output_pgn}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze and select top chess games from a PGN file.")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # --- Build Command ---
    parser_build = subparsers.add_parser("build", help="Build and populate the analysis database from a PGN file.")
    parser_build.add_argument("input_pgn", type=str, help="Path to the input PGN file.")
    parser_build.add_argument("db_file", type=str, help="Path to the SQLite database file to create.")
    parser_build.add_argument(
        "--group_by_time_control",
        action="store_true",
        help="Normalize and rank games separately within each time control group."
    )

    # --- Export Command ---
    parser_export = subparsers.add_parser("export", help="Export the top N games from the database to a new PGN file.")
    parser_export.add_argument("db_file", type=str, help="Path to the existing SQLite database file.")
    parser_export.add_argument("output_pgn", type=str, help="Path for the output PGN file.")
    parser_export.add_argument("-n", "--top_n", type=int, default=50,
                               help="Number of top games to export (default: 50).")
    parser_export.add_argument(
        "--sort_by",
        nargs='+',
        default=["quality_score:desc"],
        help="Sort order for games, e.g., 'quality_score:desc' 'game_datetime:asc' (default: 'quality_score:desc')."
    )
    parser_export.add_argument("--min_score", type=float, help="Optional: minimum quality score for exported games.")
    parser_export.add_argument("--max_score", type=float, help="Optional: maximum quality score for exported games.")

    args = parser.parse_args()

    if args.command == "build":
        build_database(args.input_pgn, args.db_file, args.group_by_time_control)
    elif args.command == "export":
        export_top_games(args.db_file, args.output_pgn, args.top_n, args.sort_by, args.min_score, args.max_score)