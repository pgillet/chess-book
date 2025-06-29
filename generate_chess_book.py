import chess.pgn
import chess.engine
import sys
import os
from pathlib import Path
from textwrap import dedent

ENGINE_PATH = "/opt/homebrew/bin/stockfish"  # Update if necessary
MAX_BOARDS_PER_PAGE = 6

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
    \usepackage{fontspec} % Required for Unicode fonts like those used by utfsym
    \usepackage{utfsym} % For \usym command to display Unicode symbols

    % IMPORTANT: You might need to install the 'utfsym' package if you don't have it.
    % Also, ensure you have a font installed on your system that contains Unicode chess symbols.
    % Common examples for a font that works well with utfsym:
    % 'Noto Serif Chess', 'Segoe UI Symbol' (on Windows), 'Symbola', 'Chess Alpha'.
    % If your font needs to be explicitly set for utfsym, you can uncomment and modify
    % the line below, replacing 'Your Chess Unicode Font Name' with the exact name
    % of the font installed on your system:
    % \setmainfont{Your Chess Unicode Font Name}
    \begin{document}
''')

LATEX_FOOTER = "\\end{document}"


def escape_latex_special_chars(text):
    """
    Escapes common LaTeX special characters in a string.
    """
    text = text.replace('\\', '\\textbackslash{}')  # Must be first!
    text = text.replace('&', '\\&')
    text = text.replace('%', '\\%')
    text = text.replace('$', '\\$')
    text = text.replace('#', '\\#')
    text = text.replace('_', '\\_')
    text = text.replace('{', '\\{')
    text = text.replace('}', '\\}')
    text = text.replace('~', '\\textasciitilde{}')
    text = text.replace('^', '\\textasciicircum{}')
    return text


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


# UPDATED: _generate_game_notation_latex to use utfsym commands
def _generate_game_notation_latex(game, notation_type):
    notation_lines = []
    board = game.board()
    moves = list(game.mainline_moves())

    notation_output = []

    for i, move in enumerate(moves):
        move_number = (i // 2) + 1
        if i % 2 == 0:  # White's move
            notation_output.append(f"{move_number}.")

        move_str = ""
        san_move_raw = board.san(move)  # Get the raw SAN first

        if notation_type == "figurine":
            # Map piece symbols to utfsym commands using their Unicode codepoints
            white_utfsym_map = {
                'P': r'\usym{2659}', 'N': r'\usym{2658}', 'B': r'\usym{2657}',
                'R': r'\usym{2656}', 'Q': r'\usym{2655}', 'K': r'\usym{2654}',
            }
            black_utfsym_map = {
                'p': r'\usym{265F}', 'n': r'\usym{265E}', 'b': r'\usym{265D}',
                'r': r'\usym{265C}', 'q': r'\usym{265B}', 'k': r'\usym{265A}',
            }

            moving_piece = board.piece_at(move.from_square)

            if moving_piece and moving_piece.piece_type != chess.PAWN:
                piece_symbol = moving_piece.symbol()

                if moving_piece.color == chess.WHITE:
                    figurine_cmd = white_utfsym_map.get(piece_symbol, "")
                else:  # chess.BLACK
                    figurine_cmd = black_utfsym_map.get(piece_symbol, "")

                if san_move_raw and san_move_raw[0].upper() in 'NBRQK':
                    # Prepend utfsym command and escape the rest of SAN
                    # Adding a space for clarity/consistency with previous solutions
                    move_str = figurine_cmd + " " + escape_latex_special_chars(san_move_raw[1:])
                else:
                    move_str = escape_latex_special_chars(san_move_raw)
            else:
                move_str = escape_latex_special_chars(san_move_raw)

        else:  # Algebraic notation (default)
            move_str = escape_latex_special_chars(san_move_raw)

        board.push(move)
        notation_output.append(move_str)

    notation_lines.append("\\small\\noindent")
    notation_lines.append(" ".join(notation_output))
    notation_lines.append("\\par\\vspace{1ex}")

    return notation_lines


def export_game_to_latex(game, game_index, output_dir, smart_moves, notation_type):
    latex = []
    board = game.board()
    moves = list(game.mainline_moves())

    try:
        current_board_for_board_display = game.board()
        processed_moves_for_display = []
        for i, move in enumerate(moves):
            processed_moves_for_display.append({
                'move': move,
                'san': current_board_for_board_display.san(move),
                'board_fen_after': current_board_for_board_display.copy().board_fen(),
                'is_smart': (i in smart_moves)
            })
            current_board_for_board_display.push(move)

    except Exception as e:
        raise ValueError(f"Error processing game {game_index}: {e}")

    # Game metadata
    header = game.headers.get("Event", f"Game {game_index}")
    white = game.headers.get("White", "White")
    black = game.headers.get("Black", "Black")
    result = game.headers.get("Result", "*")

    white_escaped = escape_latex_special_chars(white)
    black_escaped = escape_latex_special_chars(black)
    header_escaped = escape_latex_special_chars(header)

    latex.append("\\newpage")
    latex.append(f"\\section*{{{white_escaped} vs {black_escaped} ({result}) - {header_escaped}}}")

    latex.extend(_generate_game_notation_latex(game, notation_type))

    move_pairs = []
    fen_pairs = []

    temp_board_for_fen = game.board()
    for i in range(0, len(moves), 2):  # Iterate in steps of 2 (White and Black move pairs)
        current_move_pair_text = f"{(i // 2) + 1}."
        fens_in_pair = []
        is_smart_pair = False

        # White move
        if i < len(moves):
            white_move = moves[i]
            current_move_pair_text += f" {escape_latex_special_chars(temp_board_for_fen.san(white_move))}"
            temp_board_for_fen.push(white_move)
            fens_in_pair.append(temp_board_for_fen.board_fen())
            if i in smart_moves:
                is_smart_pair = True
        else:
            # If no white move for some reason at the end (shouldn't happen with proper PGN)
            continue

            # Black move
        if (i + 1) < len(moves):
            black_move = moves[i + 1]
            current_move_pair_text += f" {escape_latex_special_chars(temp_board_for_fen.san(black_move))}"
            temp_board_for_fen.push(black_move)
            fens_in_pair.append(temp_board_for_fen.board_fen())
            if (i + 1) in smart_moves:
                is_smart_pair = True
        else:
            # If only a white move in the last pair, repeat the board state after white's move
            fens_in_pair.append(fens_in_pair[0])

        if is_smart_pair:
            move_pairs.append(current_move_pair_text)
            fen_pairs.append(fens_in_pair)

    for i, (move_text, (fen1, fen2)) in enumerate(zip(move_pairs, fen_pairs)):
        if i > 0 and i % (MAX_BOARDS_PER_PAGE // 2) == 0:
            latex.append("\\newpage")

        escaped_move_text = escape_latex_special_chars(move_text)
        latex.append(f"\\textbf{{{escaped_move_text}}} \\\\[0.5ex]")
        latex.append("\\begin{tabularx}{\\linewidth}{X X}")
        latex.append(f"\\chessboard[setfen={{ {fen1} }}, boardfontsize=20pt] &")
        latex.append(f"\\chessboard[setfen={{ {fen2} }}, boardfontsize=20pt] \\\\")
        latex.append("\\end{tabularx}")
        latex.append("\\vspace{2ex}")

    game_file = output_dir / f"game_{game_index:03}.tex"
    with open(game_file, "w") as f:
        f.write("\n".join(latex))


def generate_chess_book(pgn_path, output_dir_path, notation_type="figurine"):
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
            export_game_to_latex(game, idx + 1, output_dir, smart_moves, notation_type)
            tex_master.append(f"\\input{{game_{idx + 1:03}.tex}}")
        except Exception as e:
            print(f"⚠️ Skipping corrupted game {idx + 1}: {e}")

    tex_master.append(LATEX_FOOTER)
    with open(output_dir / "chess_book.tex", "w") as f:
        f.write("\n".join(tex_master))


if __name__ == "__main__":
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python generate_chess_book.py games.pgn output_dir [notation_type]")
        print("  notation_type: 'algebraic' or 'figurine' (default)")
        sys.exit(1)

    pgn_file = sys.argv[1]
    output_dir = sys.argv[2]
    notation = "figurine"  # Default
    if len(sys.argv) == 4:
        notation = sys.argv[3].lower()
        if notation not in ["algebraic", "figurine"]:
            print("Error: notation_type must be 'algebraic' or 'figurine'.")
            sys.exit(1)

    generate_chess_book(pgn_file, output_dir, notation)