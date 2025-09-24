import argparse
import math
import os
import sqlite3
import statistics
import sys
from datetime import datetime

import chess.engine
import chess.pgn

ENGINE_PATH = "/opt/homebrew/bin/stockfish"

DB_SCHEMA = {
    "Link": "TEXT PRIMARY KEY", "Event": "TEXT", "Site": "TEXT", "Date": "TEXT",
    "Round": "TEXT", "White": "TEXT", "Black": "TEXT", "Result": "TEXT",
    "WhiteElo": "INTEGER", "BlackElo": "INTEGER", "TimeControl": "TEXT",
    "Termination": "TEXT", "game_datetime": "TIMESTAMP", "winner": "TEXT",
    "num_moves": "INTEGER", "white_cpl": "REAL", "black_cpl": "REAL",
    "avg_cpl": "REAL", "cpl_std_dev": "REAL",
    "blunders": "INTEGER", "mistakes": "INTEGER",
    "promotions": "INTEGER",        # <-- NEW COLUMN
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


def handle_export(args):
    """Handles the 'export' command: queries the DB and writes a new PGN file."""
    if not os.path.exists(args.db_file):
        print(f"Error: Database file not found at '{args.db_file}'")
        return

    print(f"Exporting top {args.top_n} games from {args.db_file}...")

    conn = create_connection(args.db_file)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM games")
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]

        # Convert rows to dicts
        games = [dict(zip(col_names, row)) for row in rows]

        if args.group_by_timecontrol:
            # Group games by time control
            grouped = {}
            for g in games:
                tc = g.get("TimeControl") or "unknown"
                grouped.setdefault(tc, []).append(g)

            all_ranked = []
            for tc, group_games in grouped.items():
                print(f"  - Normalizing {len(group_games)} games in time control: {tc}")
                # Recompute population stats for this time control group
                pop_stats = compute_population_stats(group_games)
                for g in group_games:
                    score = calculate_quality_score(g, pop_stats)
                    g["quality_score"] = score
                all_ranked.extend(group_games)

            games = all_ranked
        else:
            # Use the scores already in DB (global baseline)
            pass

        # Apply optional filters
        if args.min_score is not None:
            games = [g for g in games if g["quality_score"] >= args.min_score]
        if args.max_score is not None:
            games = [g for g in games if g["quality_score"] <= args.max_score]

        # Sort
        sort_fields = args.sort_by or ["quality_score:desc"]
        for field in reversed(sort_fields):  # apply in reverse for stable sorting
            col, order = field.split(":")
            reverse = order.lower() == "desc"
            games.sort(key=lambda g: g.get(col, 0) or 0, reverse=reverse)

        # Take top N
        selected = games[:args.top_n]

        # Write PGN
        with open(args.output_pgn, "w") as out_file:
            for g in selected:
                out_file.write(g["raw_pgn"] + "\n")
        print("Export complete.")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        if conn:
            conn.close()


# ------------------------------------------------------------
# Game analysis
# ------------------------------------------------------------

def analyze_game(game, engine):
    """Analyzes a game with Stockfish to get the CPL for each move."""
    analysis_results = []
    board = game.board()
    if not list(game.mainline_moves()):
        return None
    for move in game.mainline_moves():
        info_before = engine.analyse(board, chess.engine.Limit(depth=12))
        eval_before = info_before["score"]
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


def extract_raw_metrics(game, analysis_results, raw_pgn_str):
    """Extract unnormalized metrics from one game, including promotions."""
    headers = game.headers
    num_moves = len(list(game.mainline_moves()))

    cpls = [d['cpl'] for d in analysis_results]
    white_cpls = [d['cpl'] for d in analysis_results if d['is_white_move']]
    black_cpls = [d['cpl'] for d in analysis_results if not d['is_white_move']]

    avg_cpl = sum(cpls) / len(cpls) if cpls else 0
    cpl_std_dev = statistics.pstdev(cpls) if len(cpls) > 1 else 0
    white_cpl = sum(white_cpls) / len(white_cpls) if white_cpls else 0
    black_cpl = sum(black_cpls) / len(black_cpls) if black_cpls else 0
    blunders = sum(1 for c in cpls if c >= 200)
    mistakes = sum(1 for c in cpls if 100 <= c < 200)

    # --- New: count pawn promotions ---
    promotions = 0
    board = game.board()
    for move in game.mainline_moves():
        if move.promotion:  # promotion to queen/rook/bishop/knight
            promotions += 1
        board.push(move)

    try:
        utc_date = headers.get("UTCDate", "1970.01.01")
        utc_time = headers.get("UTCTime", "00:00:00")
        game_datetime = datetime.strptime(f"{utc_date} {utc_time}", "%Y.%m.%d %H:%M:%S")
    except ValueError:
        game_datetime = None

    result = headers.get("Result", "*")
    winner = "White" if result == "1-0" else ("Black" if result == "0-1" else "Draw")

    return {
        "headers": headers,
        "raw_pgn": raw_pgn_str,
        "num_moves": num_moves,
        "avg_cpl": avg_cpl,
        "cpl_std_dev": cpl_std_dev,
        "white_cpl": white_cpl,
        "black_cpl": black_cpl,
        "blunders": blunders,
        "mistakes": mistakes,
        "promotions": promotions,   # <-- Added metric
        "winner": winner,
        "game_datetime": game_datetime,
    }


# ------------------------------------------------------------
# Scoring (relative normalization)
# ------------------------------------------------------------

def compute_population_stats(all_metrics):
    """Compute mean and std for key metrics across dataset."""
    def safe_stats(values):
        if not values:
            return 0.0, 1.0
        return statistics.mean(values), (statistics.pstdev(values) or 1.0)

    avg_cpls   = [m["avg_cpl"]   for m in all_metrics]
    blunders   = [m["blunders"]  for m in all_metrics]
    mistakes   = [m["mistakes"]  for m in all_metrics]
    num_moves  = [m["num_moves"] for m in all_metrics]

    return {
        "avg_cpl":   safe_stats(avg_cpls),
        "blunders":  safe_stats(blunders),
        "mistakes":  safe_stats(mistakes),
        "num_moves": safe_stats(num_moves),
    }


def calculate_quality_score(metrics, pop_stats, verbose=False):
    """
    Calculate a normalized, non-linear, weighted score for one game.
    """
    avg_cpl     = metrics["avg_cpl"]
    blunders    = metrics["blunders"]
    mistakes    = metrics["mistakes"]
    num_moves   = metrics["num_moves"]
    promotions  = metrics.get("promotions", 0)  # <-- FIX: safely get promotions

    mean_cpl, std_cpl         = pop_stats["avg_cpl"]
    mean_blunders, std_blunders = pop_stats["blunders"]
    mean_mistakes, std_mistakes = pop_stats["mistakes"]
    mean_moves, std_moves       = pop_stats["num_moves"]

    # z-scores (relative performance)
    z_cpl = (avg_cpl - mean_cpl) / (std_cpl + 1e-6)
    z_blunders = (blunders - mean_blunders) / (std_blunders + 1e-6)
    z_mistakes = (mistakes - mean_mistakes) / (std_mistakes + 1e-6)
    z_moves = (num_moves - mean_moves) / (std_moves + 1e-6)

    # penalties (non-linear)
    blunder_penalty = math.exp(-blunders / (mean_blunders + 1))
    mistake_penalty = math.exp(-mistakes / (mean_mistakes + 1))
    cpl_penalty = max(0, 1 - math.sqrt(avg_cpl / (mean_cpl + 1)))
    moves_penalty = math.exp(-abs(z_moves))

    # clamp relative components
    rel_cpl = max(1e-6, 1 - z_cpl)
    rel_blunders = max(1e-6, 1 - z_blunders)
    rel_mistakes = max(1e-6, 1 - z_mistakes)

    # weighted geometric mean
    quality_score = (
        (cpl_penalty ** 0.25) * (rel_cpl ** 0.10) *
        (blunder_penalty ** 0.20) * (rel_blunders ** 0.05) *
        (mistake_penalty ** 0.15) * (rel_mistakes ** 0.05) *
        (moves_penalty ** 0.20)
    )

    final_score = max(0, min(100, quality_score * 100))

    # contextual bonuses/penalties
    termination = metrics["headers"].get("Termination", "").lower()
    result = metrics["headers"].get("Result", "*")
    white_elo = metrics["headers"].get("WhiteElo")
    black_elo = metrics["headers"].get("BlackElo")

    if "checkmate" in termination:
        final_score = min(100, final_score + 5)
    if "time" in termination:
        final_score *= 0.8
    if "repetition" in termination or "50 move" in termination:
        final_score *= 0.9

    try:
        we, be = int(white_elo), int(black_elo)
        if result == "1-0" and we < be:
            final_score = min(100, final_score + 3)
        elif result == "0-1" and be < we:
            final_score = min(100, final_score + 3)
    except (TypeError, ValueError):
        pass

    if promotions > 0:
        final_score = min(100, final_score + 2 * promotions)

    # debug printing
    if verbose:
        print(f"  Debug: Game {metrics['headers'].get('Link', '')}")
        print(f"    CPL: {avg_cpl:.2f}, mean={mean_cpl:.2f}, z={z_cpl:.2f}, penalty={cpl_penalty:.3f}, rel={rel_cpl:.3f}")
        print(f"    Blunders: {blunders}, mean={mean_blunders:.2f}, z={z_blunders:.2f}, penalty={blunder_penalty:.3f}, rel={rel_blunders:.3f}")
        print(f"    Mistakes: {mistakes}, mean={mean_mistakes:.2f}, z={z_mistakes:.2f}, penalty={mistake_penalty:.3f}, rel={rel_mistakes:.3f}")
        print(f"    Moves: {num_moves}, mean={mean_moves:.2f}, z={z_moves:.2f}, penalty={moves_penalty:.3f}")
        print(f"    Promotions: {promotions} → bonus={promotions * 2}")
        print(f"    Bonuses/Penalties: "
              f"checkmate={'+5' if 'checkmate' in termination else '0'}, "
              f"time={'-20%' if 'time' in termination else '0'}, "
              f"draw={'-10%' if 'repetition' in termination or '50 move' in termination else '0'}")
        print(f"    => Final Score: {final_score:.2f}\n")

    return final_score




# ------------------------------------------------------------
# Build process (two-pass)
# ------------------------------------------------------------

def handle_build(args):
    """Handles the 'build' command: reads PGN, analyzes, and populates the database."""
    print(f"Building database at: {args.db_file}")
    if os.path.exists(args.db_file):
        os.remove(args.db_file)
        print("  - Overwriting existing database file.")

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

    # --- Pass 1: Collect raw metrics for all games ---
    all_metrics = []
    with open(args.input_pgn, "r", encoding="utf-8") as pgn_file:
        game_num = 1
        while True:
            start_pos = pgn_file.tell()
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break
            end_pos = pgn_file.tell()
            pgn_file.seek(start_pos)
            raw_pgn = pgn_file.read(end_pos - start_pos)
            pgn_file.seek(end_pos)

            if not raw_pgn.strip():
                continue

            print(f"Analyzing game {game_num} ({game.headers.get('Link', '')})...")
            try:
                analysis = analyze_game(game, engine)
                if analysis:
                    m = extract_raw_metrics(game, analysis, raw_pgn)
                    all_metrics.append(m)
            except Exception as e:
                print(f"  - Could not analyze game {game_num}. Skipping. Error: {e}")

            game_num += 1

    # --- Group by time control ---
    groups = {}
    for m in all_metrics:
        tc = m["headers"].get("TimeControl", "unknown")
        groups.setdefault(tc, []).append(m)

    # --- Pass 2: Compute stats + scores per group ---
    all_scores = []
    for tc, group in groups.items():
        print(f"\nScoring {len(group)} games in time control group: {tc}")
        pop_stats = compute_population_stats(group)

        for m in group:
            score = calculate_quality_score(m, pop_stats, verbose=True)
            all_scores.append(score)

            headers = m["headers"]
            game_data = {
                "Link": headers.get("Link"),
                "Event": headers.get("Event"),
                "Site": headers.get("Site"),
                "Date": headers.get("Date"),
                "Round": headers.get("Round"),
                "White": headers.get("White"),
                "Black": headers.get("Black"),
                "Result": headers.get("Result"),
                "WhiteElo": headers.get("WhiteElo"),
                "BlackElo": headers.get("BlackElo"),
                "TimeControl": headers.get("TimeControl"),
                "Termination": headers.get("Termination"),
                "game_datetime": m["game_datetime"],
                "winner": m["winner"],
                "num_moves": m["num_moves"],
                "white_cpl": m["white_cpl"],
                "black_cpl": m["black_cpl"],
                "avg_cpl": m["avg_cpl"],
                "cpl_std_dev": m["cpl_std_dev"],
                "blunders": m["blunders"],
                "mistakes": m["mistakes"],
                "promotions": m["promotions"],
                "quality_score": score,
                "raw_pgn": m["raw_pgn"],
            }
            insert_game(conn, game_data)

    conn.commit()
    conn.close()
    engine.quit()

    # --- Summary of scores ---
    if all_scores:
        avg_score = sum(all_scores) / len(all_scores)
        min_score = min(all_scores)
        max_score = max(all_scores)
        print("\n=== Quality Score Summary ===")
        print(f"  Games analyzed: {len(all_scores)}")
        print(f"  Min score: {min_score:.2f}")
        print(f"  Max score: {max_score:.2f}")
        print(f"  Avg score: {avg_score:.2f}")

        # Histogram (bucketed by 20s)
        buckets = [0] * 5
        for s in all_scores:
            if s < 20: buckets[0] += 1
            elif s < 40: buckets[1] += 1
            elif s < 60: buckets[2] += 1
            elif s < 80: buckets[3] += 1
            else: buckets[4] += 1
        print(f"  Distribution:")
        print(f"    0–19:  {buckets[0]}")
        print(f"    20–39: {buckets[1]}")
        print(f"    40–59: {buckets[2]}")
        print(f"    60–79: {buckets[3]}")
        print(f"    80–100:{buckets[4]}")
        print("=============================\n")

    print("Database build complete.")


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
    parser_export.add_argument("--min_score", type=float, help="Optional: minimum quality score for exported games.")
    parser_export.add_argument("--max_score", type=float, help="Optional: maximum quality score for exported games.")
    parser_export.add_argument(
        "--group_by_timecontrol",
        action="store_true",
        help="Normalize and rank games separately within each time control group."
    )

    args = parser.parse_args()

    if args.command == "build":
        handle_build(args)
    elif args.command == "export":
        handle_export(args)
