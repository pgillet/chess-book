import argparse
import chess.pgn
import chess.engine
import sys
import sqlite3
from datetime import datetime
import os
import math  # Needed for standard deviation calculation

# --- CONFIGURATION ---
ENGINE_PATH = "/opt/homebrew/bin/stockfish"

# --- DATABASE SCHEMA ---
DB_SCHEMA = {
    "Link": "TEXT PRIMARY KEY", "Event": "TEXT", "Site": "TEXT", "Date": "TEXT",
    "Round": "TEXT", "White": "TEXT", "Black": "TEXT", "Result": "TEXT",
    "WhiteElo": "INTEGER", "BlackElo": "INTEGER", "TimeControl": "TEXT",
    "Termination": "TEXT", "game_datetime": "TIMESTAMP", "winner": "TEXT",
    "num_moves": "INTEGER", "white_cpl": "REAL", "black_cpl": "REAL",
    "avg_cpl": "REAL", "cpl_std_dev": "REAL",  # New metric
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
        c.execute("DROP TABLE IF EXISTS games;")
        c.execute(sql_create_table)
    except sqlite3.Error as e:
        print(e)


def insert_game(conn, game_data):
    """Insert a new game into the games table."""
    columns = ', '.join([f'"{col}"' for col in game_data.keys()])
    placeholders = ':' + ', :'.join(game_data.keys())
    sql = f'INSERT INTO games ({columns}) VALUES ({placeholders})'
    try:
        cur = conn.cursor()
        cur.execute(sql, game_data)
        return cur.lastrowid
    except sqlite3.IntegrityError:
        print(f"  - SKIPPING: Game with link {game_data.get('Link')} already exists.")
        return None
    except Exception as e:
        print(f"  - ERROR inserting game: {e}")
        return None


# --- GAME ANALYSIS FUNCTIONS ---

def analyze_game(game, engine):
    """Analyzes a game with Stockfish to get the CPL for each move."""
    analysis_results = []
    board = game.board()
    if not list(game.mainline_moves()):
        return None

    for move in game.mainline_moves():
        info = engine.analyse(board, chess.engine.Limit(depth=12))
        eval_before = info["score"]
        board.push(move)
        info_after = engine.analyse(board, chess.engine.Limit(depth=12))
        eval_after = info_after["score"]

        cpl = 0
        if not eval_before.is_mate() and not eval_after.is_mate():
            cp_before = eval_before.white().cp
            cp_after = eval_after.white().cp
            if board.turn == chess.BLACK:  # White just moved
                cpl = max(0, cp_before - cp_after)
            else:  # Black just moved
                cpl = max(0, cp_after - cp_before)

        analysis_results.append({'cpl': cpl, 'is_white_move': board.turn == chess.BLACK})
    return analysis_results


def calculate_game_score(game, analysis_results):
    """
    Calculates a 'quality score' and returns a detailed dictionary of metrics,
    disqualifying games that are too short.
    """
    if not analysis_results:
        return 0, {}

    headers = game.headers
    moves = list(game.mainline_moves())
    num_moves = len(moves)

    # Disqualify very short games
    MINIMUM_MOVES = 20  # 10 full moves
    if num_moves < MINIMUM_MOVES:
        # Return a very low score to ensure this game is never in the top N
        score = -1000
        metrics = {
            "white": headers.get("White", "?"), "black": headers.get("Black", "?"),
            "result": headers.get("Result", "*"), "final_score": score, "avg_cpl": 0,
            "cpl_std_dev": 0, "blunders": 0, "mistakes": 0, "length_score": -1000,
            "result_bonus": 0, "consistency_bonus": 0, "white_cpl": 0, "black_cpl": 0
        }
        return score, metrics

    # --- METRICS ---
    white_cpls = [d['cpl'] for d in analysis_results if d['is_white_move']]
    black_cpls = [d['cpl'] for d in analysis_results if not d['is_white_move']]
    white_cpl = sum(white_cpls) / len(white_cpls) if white_cpls else 0
    black_cpl = sum(black_cpls) / len(black_cpls) if black_cpls else 0
    avg_cpl = (white_cpl + black_cpl) / 2

    variance = ((white_cpl - avg_cpl) ** 2 + (black_cpl - avg_cpl) ** 2) / 2
    cpl_std_dev = math.sqrt(variance)

    blunders = sum(1 for d in analysis_results if d['cpl'] >= 200)
    mistakes = sum(1 for d in analysis_results if 100 <= d['cpl'] < 200)

    # Bonus for ideal length (no penalty here anymore)
    length_score = 10 if 30 <= num_moves <= 120 else 0

    result_bonus = 20 if "checkmate" in headers.get("Termination", "").lower() else (
        5 if headers.get("Result") in ["1-0", "0-1"] else 0)

    # --- SCORING FORMULA ---
    cpl_score = (100 - avg_cpl)
    excitement_score = (blunders * 2) + (mistakes * 1)
    consistency_bonus = max(0, 15 - cpl_std_dev)

    final_score = cpl_score + excitement_score + length_score + result_bonus + consistency_bonus

    metrics = {
        "white": headers.get("White", "?"), "black": headers.get("Black", "?"),
        "result": headers.get("Result", "*"), "avg_cpl": avg_cpl,
        "cpl_std_dev": cpl_std_dev, "blunders": blunders, "mistakes": mistakes,
        "length_score": length_score,
        "result_bonus": result_bonus,
        "consistency_bonus": consistency_bonus, "final_score": final_score,
        "white_cpl": white_cpl, "black_cpl": black_cpl
    }

    return final_score, metrics


def process_game(game, analysis_results, raw_pgn_str):
    """
    Processes game headers and analysis.
    Returns two dictionaries: one for the DB, and one with detailed metrics for printing.
    """
    score, metrics = calculate_game_score(game, analysis_results)
    if not metrics:
        return None, None

    headers = game.headers
    # --- Prepare data for the database ---
    game_data = {col: headers.get(col, None) for col in DB_SCHEMA if col in headers}

    game_data['raw_pgn'] = raw_pgn_str
    try:
        utc_date = headers.get("UTCDate", "1970.01.01")
        utc_time = headers.get("UTCTime", "00:00:00")
        game_data['game_datetime'] = datetime.strptime(f"{utc_date} {utc_time}", "%Y.%m.%d %H:%M:%S")
    except ValueError:
        game_data['game_datetime'] = None

    result = headers.get("Result", "*")
    game_data['winner'] = "White" if result == "1-0" else ("Black" if result == "0-1" else "Draw")

    # Add analysis metrics to the database dictionary
    game_data['num_moves'] = len(list(game.mainline_moves()))
    game_data['white_cpl'] = metrics['white_cpl']
    game_data['black_cpl'] = metrics['black_cpl']
    game_data['avg_cpl'] = metrics['avg_cpl']
    game_data['cpl_std_dev'] = metrics['cpl_std_dev']
    game_data['blunders'] = metrics['blunders']
    game_data['mistakes'] = metrics['mistakes']
    game_data['quality_score'] = score

    # Return both the DB-ready data and the detailed metrics for printing
    return game_data, metrics


def print_game_analysis_summary(metrics):
    """
    Prints a formatted summary of the game's analysis metrics to the console.
    """
    if not metrics:
        return

    print("-" * 40)
    print(f"  Game: {metrics['white']} vs {metrics['black']} ({metrics['result']})")
    print(f"  Overall Score: {metrics['final_score']:.2f}")
    print("  --- Metrics ---")
    print(f"  Avg. CPL: {metrics['avg_cpl']:.2f} (lower is better)")
    print(f"  CPL Std Dev: {metrics['cpl_std_dev']:.2f} (lower indicates more balanced play)")
    print(f"  Blunders: {metrics['blunders']}")
    print(f"  Mistakes: {metrics['mistakes']}")
    # FIX: Changed 'length_bonus' to 'length_score' to match the new key.
    print(f"  Length Score: {metrics['length_score']}")
    print(f"  Result Bonus: {metrics['result_bonus']}")
    print(f"  Consistency Bonus: {metrics['consistency_bonus']:.2f}")
    print("-" * 40 + "\n")


def handle_build(args):
    """Handles the 'build' command: reads PGN, analyzes, and populates the database."""
    print(f"Building database at: {args.db_file}")
    if os.path.exists(args.db_file):
        print("  - Overwriting existing database file.")
        os.remove(args.db_file)

    conn = create_connection(args.db_file)
    if conn is None:
        print("Error! Cannot create the database connection.")
        return
    create_table(conn)

    try:
        engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
    except FileNotFoundError:
        print(f"Error: Stockfish engine not found at '{ENGINE_PATH}'")
        sys.exit(1)

    with open(args.input_pgn, "r", encoding="utf-8") as pgn_file:
        game_num = 1
        while True:
            start_pos = pgn_file.tell()
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break

            end_pos = pgn_file.tell()
            pgn_file.seek(start_pos)
            pgn_str = pgn_file.read(end_pos - start_pos)
            pgn_file.seek(end_pos)

            if not pgn_str.strip():
                continue

            print(f"Analyzing game {game_num} ({game.headers.get('Link', '')})...")
            try:
                analysis = analyze_game(game, engine)
                if analysis:
                    # Unpack the two dictionaries returned by the updated function
                    game_data, metrics_for_print = process_game(game, analysis, pgn_str)
                    if game_data:
                        insert_game(conn, game_data)
                        print_game_analysis_summary(metrics_for_print)  # Use the metrics dict for printing
            except Exception as e:
                print(f"  - Could not analyze game {game_num}. Skipping. Error: {e}")

            game_num += 1

    conn.commit()
    conn.close()
    engine.quit()
    print("\nDatabase build complete.")


def handle_export(args):
    """Handles the 'export' command: queries the DB and writes a new PGN file."""
    if not os.path.exists(args.db_file):
        print(f"Error: Database file not found at '{args.db_file}'")
        return

    print(f"Exporting top {args.top_n} games from {args.db_file}...")

    # Build the ORDER BY clause
    order_by_parts = []
    for sort_criterion in args.sort_by:
        parts = sort_criterion.split(':')
        if len(parts) != 2 or parts[0] not in DB_SCHEMA or parts[1].lower() not in ['asc', 'desc']:
            print(f"Error: Invalid sort criterion '{sort_criterion}'. Must be 'column:asc' or 'column:desc'.")
            return
        order_by_parts.append(f'"{parts[0]}" {parts[1].upper()}')

    order_by_clause = "ORDER BY " + ", ".join(order_by_parts) if order_by_parts else ""

    sql_query = f"SELECT raw_pgn FROM games {order_by_clause} LIMIT {args.top_n};"
    print(f"  - Executing SQL: {sql_query}")

    conn = create_connection(args.db_file)
    try:
        cur = conn.cursor()
        cur.execute(sql_query)
        rows = cur.fetchall()

        print(f"  - Found {len(rows)} games. Writing to {args.output_pgn}...")
        with open(args.output_pgn, "w") as out_file:
            for row in rows:
                out_file.write(row[0] + "\n")
        print("Export complete.")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze a PGN file and store results in a database, then export top games.")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # --- Build Command ---
    parser_build = subparsers.add_parser("build", help="Build and populate the analysis database from a PGN file.")
    parser_build.add_argument("input_pgn", type=str, help="Path to the input PGN file.")
    parser_build.add_argument("db_file", type=str, help="Path to the SQLite database file to create.")

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

    args = parser.parse_args()

    if args.command == "build":
        handle_build(args)
    elif args.command == "export":
        handle_export(args)