import argparse
import chess.pgn
import chess.engine
import sys

# --- CONFIGURATION ---
ENGINE_PATH = "/opt/homebrew/bin/stockfish"


def calculate_game_score(game, analysis_results):
    """
    Calculates a 'quality score' and returns a detailed dictionary of metrics.
    """
    if not analysis_results:
        return 0, {}

    headers = game.headers
    moves = list(game.mainline_moves())
    num_moves = len(moves)

    # --- METRICS ---
    white_cpls = [d['cpl'] for d in analysis_results if d['is_white_move']]
    black_cpls = [d['cpl'] for d in analysis_results if not d['is_white_move']]
    white_cpl = sum(white_cpls) / len(white_cpls) if white_cpls else 0
    black_cpl = sum(black_cpls) / len(black_cpls) if black_cpls else 0
    avg_cpl = (white_cpl + black_cpl) / 2

    blunders = sum(1 for d in analysis_results if d['cpl'] >= 200)
    mistakes = sum(1 for d in analysis_results if 100 <= d['cpl'] < 200)

    length_bonus = 10 if 20 <= num_moves <= 120 else 0

    result_bonus = 0
    termination = headers.get("Termination", "").lower()
    if "checkmate" in termination:
        result_bonus = 20
    elif headers.get("Result") in ["1-0", "0-1"]:
        result_bonus = 5

    # --- SCORING FORMULA ---
    cpl_score = (100 - avg_cpl)
    excitement_score = (blunders * 2) + (mistakes * 1)
    final_score = cpl_score + excitement_score + length_bonus + result_bonus

    metrics = {
        "white": headers.get("White", "?"),
        "black": headers.get("Black", "?"),
        "result": headers.get("Result", "*"),
        "avg_cpl": avg_cpl,
        "blunders": blunders,
        "mistakes": mistakes,
        "length_bonus": length_bonus,
        "result_bonus": result_bonus,
        "final_score": final_score
    }

    return final_score, metrics


def analyze_game(game, engine):
    """
    Analyzes a single game with Stockfish to get the CPL for each move.
    """
    analysis_results = []
    board = game.board()
    moves = list(game.mainline_moves())

    if not moves:
        return None

    for move in moves:
        analysis_before = engine.analyse(board, chess.engine.Limit(depth=12))
        eval_before = analysis_before["score"]

        board.push(move)
        analysis_after = engine.analyse(board, chess.engine.Limit(depth=12))
        eval_after = analysis_after["score"]

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
    print(f"  Blunders: {metrics['blunders']}")
    print(f"  Mistakes: {metrics['mistakes']}")
    print(f"  Length Bonus: {metrics['length_bonus']}")
    print(f"  Result Bonus: {metrics['result_bonus']}")
    print("-" * 40 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Select the top N games from a PGN file based on analysis."
    )
    parser.add_argument(
        "input_file",
        type=str,
        help="Path to the input PGN file with many games."
    )
    parser.add_argument(
        "output_file",
        type=str,
        help="Path to the output PGN file for the top N games."
    )
    parser.add_argument(
        "n",
        type=int,
        help="The number of top games to select."
    )
    args = parser.parse_args()

    try:
        engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
    except FileNotFoundError:
        print(f"Error: Stockfish engine not found at '{ENGINE_PATH}'")
        sys.exit(1)

    all_games = []
    with open(args.input_file) as pgn_file:
        game_num = 1
        while True:
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break

            print(f"Analyzing game {game_num}...")
            try:
                analysis = analyze_game(game, engine)
                if analysis:
                    score, metrics = calculate_game_score(game, analysis)
                    all_games.append((score, game))
                    print_game_analysis_summary(metrics)  # Print summary
            except Exception as e:
                print(f"  Could not analyze game {game_num}. Skipping. Error: {e}")

            game_num += 1

    all_games.sort(key=lambda x: x[0], reverse=True)
    top_n_games = all_games[:args.n]

    print("\nSorting top games by date...")
    top_n_games.sort(key=lambda x: x[1].headers.get("Date", "9999.99.99"))

    print(f"\nWriting the top {len(top_n_games)} games to {args.output_file}...")
    with open(args.output_file, "w") as out_pgn:
        for score, game in top_n_games:
            print(game, file=out_pgn, end="\n\n")

    engine.quit()
    print("Done.")


if __name__ == "__main__":
    main()