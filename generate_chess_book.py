import chess.pgn
import chess.engine
import sys
import os
from pathlib import Path
from textwrap import dedent

ENGINE_PATH = "/opt/homebrew/bin/stockfish"  # Update if necessary
MAX_BOARDS_PER_PAGE = 8

LATEX_HEADER = dedent(r'''
    \documentclass[10pt]{article}
    \usepackage[margin=0.7in]{geometry}
    \usepackage{chessboard}
    \usepackage{multicol}
    \usepackage{fancyhdr}
    \usepackage{titlesec}
    \usepackage{parskip}
    \usepackage{tabularx}
    \titleformat{\section}{\normalfont\Large\bfseries}{}{0pt}{}
    \setlength{\parindent}{0pt}
    \pagestyle{fancy}
    \fancyhf{}
    \rhead{\thepage}
    \begin{document}
''')

LATEX_FOOTER = "\\end{document}"

def is_tactical(board, move):
    return board.is_capture(move) or board.gives_check(move)

def find_smart_moves(game):
    smart_moves = set()
    try:
        with chess.engine.SimpleEngine.popen_uci(ENGINE_PATH) as engine:
            board = game.board()
            for i, move in enumerate(game.mainline_moves()):
                info = engine.analyse(board, chess.engine.Limit(depth=15))
                best = info["pv"][0]
                if best != move:
                    smart_moves.add(i)
                board.push(move)
    except Exception as e:
        print(f"⚠️ Engine analysis failed: {e}")
    return smart_moves

def export_game_to_latex(game, game_index, output_dir, smart_moves):
    latex = []
    board = game.board()
    moves = list(game.mainline_moves())

    move_pairs = []
    fen_pairs = []

    try:
        i = 0
        while i < len(moves):
            move_text = f"{(i // 2) + 1}."
            fens = []

            # White move
            move_text += f" {board.san(moves[i])}"
            board.push(moves[i])
            fens.append(board.board_fen())
            i += 1

            # Black move
            if i < len(moves):
                move_text += f" {board.san(moves[i])}"
                board.push(moves[i])
                fens.append(board.board_fen())
                i += 1
            else:
                fens.append(fens[0])  # Repeat White position if no Black move

            if (i - 1) in smart_moves or (i - 2) in smart_moves:
                move_pairs.append(move_text)
                fen_pairs.append(fens)

    except Exception as e:
        raise ValueError(f"Error processing game {game_index}: {e}")

    # Game metadata
    header = game.headers.get("Event", f"Game {game_index}")
    white = game.headers.get("White", "White")
    black = game.headers.get("Black", "Black")
    result = game.headers.get("Result", "*")

    latex.append(f"\\section*{{{white} vs {black} ({result}) - {header}}}")

    for i, (move_text, (fen1, fen2)) in enumerate(zip(move_pairs, fen_pairs)):
        if i > 0 and i % (MAX_BOARDS_PER_PAGE // 2) == 0:
            latex.append("\\newpage")

        latex.append(f"\\textbf{{{move_text}}} \\\\[0.5ex]")
        latex.append("\\begin{tabularx}{\\linewidth}{X X}")
        latex.append(f"\\chessboard[setfen={{ {fen1} }}, boardfontsize=20pt] &")
        latex.append(f"\\chessboard[setfen={{ {fen2} }}, boardfontsize=20pt] \\\\")
        latex.append("\\end{tabularx}")
        latex.append("\\vspace{2ex}")

    game_file = output_dir / f"game_{game_index:03}.tex"
    with open(game_file, "w") as f:
        f.write("\n".join(latex))


def generate_chess_book(pgn_path, output_dir_path):
    pgn_path = Path(pgn_path)
    output_dir = Path(output_dir_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(pgn_path) as f:
        games = []
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            games.append(game)

    tex_master = [LATEX_HEADER]
    for idx, game in enumerate(games):
        try:
            smart_moves = find_smart_moves(game)
            export_game_to_latex(game, idx + 1, output_dir, smart_moves)
            tex_master.append(f"\\input{{game_{idx + 1:03}.tex}}")
        except Exception as e:
            print(f"⚠️ Skipping corrupted game {idx + 1}: {e}")

    tex_master.append(LATEX_FOOTER)
    with open(output_dir / "chess_book.tex", "w") as f:
        f.write("\n".join(tex_master))

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python generate_chess_book.py games.pgn output_dir")
        sys.exit(1)

    generate_chess_book(sys.argv[1], sys.argv[2])
