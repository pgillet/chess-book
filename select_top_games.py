import argparse
import io

import chess.pgn
import chess.engine
import sys
import sqlite3
from datetime import datetime
import os

# --- CONFIGURATION ---
ENGINE_PATH = "/opt/homebrew/bin/stockfish"

# --- DATABASE SCHEMA ---
# This dictionary defines the table schema.
# Keys are the desired column names.
# Values are their corresponding SQL data types.
DB_SCHEMA = {
    "Link": "TEXT PRIMARY KEY",
    "Event": "TEXT",
    "Site": "TEXT",
    "Date": "TEXT",
    "Round": "TEXT",
    "White": "TEXT",
    "Black": "TEXT",
    "Result": "TEXT",
    "WhiteElo": "INTEGER",
    "BlackElo": "INTEGER",
    "TimeControl": "TEXT",
    "Termination": "TEXT",
    "game_datetime": "TIMESTAMP",
    "winner": "TEXT",
    "num_moves": "INTEGER",
    "white_cpl": "REAL",
    "black_cpl": "REAL",
    "avg_cpl": "REAL",
    "blunders": "INTEGER",
    "mistakes": "INTEGER",
    "quality_score": "REAL",
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
    """Analyzes a game with Stockfish to get CPL for each move."""
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


def process_game(game, analysis_results, raw_pgn_str):
    """Processes game headers and analysis to create a dictionary for the DB."""
    if not analysis_results:
        return None

    headers = game.headers
    num_moves = len(list(game.mainline_moves()))

    # --- Collect all data for the database row ---
    game_data = {col: headers.get(col, None) for col in DB_SCHEMA if col in headers}

    # Add raw PGN
    game_data['raw_pgn'] = raw_pgn_str

    # Add deduced columns
    try:
        utc_date = headers.get("UTCDate", "1970.01.01")
        utc_time = headers.get("UTCTime", "00:00:00")
        game_data['game_datetime'] = datetime.strptime(f"{utc_date} {utc_time}", "%Y.%m.%d %H:%M:%S")
    except ValueError:
        game_data['game_datetime'] = None  # Handle malformed dates

    result = headers.get("Result", "*")
    if result == "1-0":
        game_data['winner'] = "White"
    elif result == "0-1":
        game_data['winner'] = "Black"
    else:
        game_data['winner'] = "Draw"

    # Add analysis metrics
    game_data['num_moves'] = num_moves
    white_cpls = [d['cpl'] for d in analysis_results if d['is_white_move']]
    black_cpls = [d['cpl'] for d in analysis_results if not d['is_white_move']]
    game_data['white_cpl'] = sum(white_cpls) / len(white_cpls) if white_cpls else 0
    game_data['black_cpl'] = sum(black_cpls) / len(black_cpls) if black_cpls else 0
    game_data['avg_cpl'] = (game_data['white_cpl'] + game_data['black_cpl']) / 2
    game_data['blunders'] = sum(1 for d in analysis_results if d['cpl'] >= 200)
    game_data['mistakes'] = sum(1 for d in analysis_results if 100 <= d['cpl'] < 200)

    # Calculate quality score
    length_bonus = 10 if 20 <= num_moves <= 120 else 0
    result_bonus = 20 if "checkmate" in headers.get("Termination", "").lower() else (
        5 if result in ["1-0", "0-1"] else 0)
    game_data['quality_score'] = (100 - game_data['avg_cpl']) + (game_data['blunders'] * 2) + (
                game_data['mistakes'] * 1) + length_bonus + result_bonus

    return game_data


# --- MAIN HANDLERS ---

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

    # --- START OF FIX ---
    # This new method robustly reads one game at a time while capturing its raw text.
    with open(args.input_pgn, "r", encoding="utf-8") as pgn_file:
        game_num = 1
        while True:
            # Get the starting position of the game in the file
            start_pos = pgn_file.tell()

            # Use the library to read the game, which advances the file pointer
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break  # End of file

            # Get the ending position
            end_pos = pgn_file.tell()

            # Go back to the start and read the raw text for this game
            pgn_file.seek(start_pos)
            pgn_str = pgn_file.read(end_pos - start_pos)

            # Ensure the file pointer is set for the next read_game() call
            pgn_file.seek(end_pos)
            # --- END OF FIX ---

            if not pgn_str.strip():
                continue

            print(f"Analyzing game {game_num} ({game.headers.get('Link', '')})...")
            try:
                analysis = analyze_game(game, engine)
                if analysis:
                    game_data = process_game(game, analysis, pgn_str)
                    if game_data:
                        insert_game(conn, game_data)
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