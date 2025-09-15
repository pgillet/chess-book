# Chess Book Generator ♟️

This project provides a complete toolchain to fetch your chess games from Chess.com, analyze and select the best ones, and compile them into a beautifully formatted, print-ready PDF book.

The process is broken down into three main steps:

1.  **Fetch Games**: Download all your games from Chess.com.
2.  **Analyze & Select**: Analyze every game, calculate quality metrics, and select the top games based on your criteria.
3.  **Generate Book**: Compile the selected games into a professional PDF.

-----

## Prerequisites

Before you begin, ensure you have the following software installed on your system.

  * **Python**: Version 3.13 or newer.
  * **Python Libraries**: You can install the required libraries using pip:
    ```shell
    pip install requests python-chess
    ```
  * **Stockfish Chess Engine**: The analysis script requires the Stockfish engine. You can download it from the [official Stockfish website](https://stockfishchess.org/download/). Make sure to update the `ENGINE_PATH` variable in the scripts to point to your Stockfish executable.
  * **LaTeX Distribution**: To compile the `.tex` files into a PDF, you need a LaTeX distribution.
      * **Windows**: [MiKTeX](https://miktex.org/download)
      * **macOS**: [MacTeX](https://www.tug.org/mactex/downloading.html)
      * **Linux**: TeX Live (usually available through your package manager, e.g., `sudo apt-get install texlive-full`).

-----

## Step 1: Fetch Your Games from Chess.com

First, download all your played games into a single PGN file. The `chesscom_fetch.py` script handles this by accessing the public Chess.com API.

### **Usage**

Run the following command in your terminal, replacing `<username>` with your Chess.com username and `<output_file.pgn>` with your desired output file name.

```shell
python chesscom_fetch.py <username> -o <output_file.pgn>
```

#### **Example**

```shell
python chesscom_fetch.py Krystof126 -o games-full.pgn
```

This will create a file named `games-full.pgn` containing all of your games.

-----

## Step 2: Analyze and Select Top Games

This step uses the `select_top_games.py` script to analyze the PGN file from Step 1, calculate metrics like average centipawn loss and a quality score for each game, and store everything in a SQLite database. Once the database is built, you can export the top games based on your criteria.

### **2.1 - Build the Analysis Database**

This command reads your large PGN file, analyzes each game with the Stockfish engine, and populates a new SQLite database. **This process can take a significant amount of time.**

```shell
python select_top_games.py build <input_pgn_file> <database_file>
```

#### **Example**

```shell
python select_top_games.py build games-full.pgn analysis.db
```

This creates the `analysis.db` file, which you can reuse for future exports without re-analyzing the games.

### **2.2 - Export a Selection of Games**

Once the database is built, you can run fast queries to export a curated PGN file containing only the games you want in your book.

```shell
python select_top_games.py export <database_file> <output_pgn_file> -n <number> --sort_by <criteria>
```

#### **Examples**

  * **To get the top 5 best-quality games:**
    ```shell
    python select_top_games.py export analysis.db top_5_quality.pgn -n 5 --sort_by quality_score:desc
    ```
  * **To get the 10 most recent checkmate wins:**
    ```shell
    python select_top_games.py export analysis.db top_10_recent_mates.pgn -n 10 --sort_by game_datetime:desc
    ```

This will generate a smaller, curated PGN file (e.g., `top_5_quality.pgn`) that you will use in the final step.

### **2.3 - Advanced Selection via Direct SQL Querying**

For the most powerful and fine-tuned game selections, you can query the SQLite database (`analysis.db`) directly using any standard SQL client (like `sqlite3` on the command line, or a graphical tool like DB Browser for SQLite).

The main table is named `games`, and it contains useful columns such as `quality_score`, `winner`, `Termination`, `num_moves`, `avg_cpl`, `WhiteElo`, and `BlackElo`.

#### **Example 1: Select top 10 checkmate wins against strong opponents (rating \> 1500)**

```sql
SELECT raw_pgn FROM games
WHERE ((White = 'Krystof126' AND Winner = 'White' AND BlackElo > 1000) 
    OR (Black = 'Krystof126' AND Winner = 'Black' AND WhiteElo > 1000)) 
  AND Termination LIKE '%by checkmate'
ORDER BY quality_score DESC
LIMIT 10;
```

#### **Example 2: Select the 5 longest games (most moves) where your accuracy was high (avg CPL \< 40)**

```sql
SELECT raw_pgn FROM games
WHERE White = 'Krystof126' AND white_cpl < 40
ORDER BY num_moves DESC
LIMIT 5;
```

#### **Example 3: Select 5 interesting draws (stalemate or repetition)**

```sql
SELECT raw_pgn FROM games
WHERE Result = '1/2-1/2'
  AND (Termination LIKE '%repetition%' OR Termination LIKE '%stalemate%')
ORDER BY game_datetime DESC
LIMIT 5;
```

-----

## Step 3: Generate the PDF Chess Book

The final step uses the `generate_chess_book.py` script to convert your selected PGN file into a PDF book. This script offers many options to customize the final output.

### **Usage**

```shell
python generate_chess_book.py <input_pgn_file> <output_dir> [options]
```

### **Common Options**

  * `--title`: The title of the book.
  * `--subtitle`: The subtitle of the book.
  * `--author`: The author's name.
  * `--language <en|fr>`: The language for the book's text.
  * `--paper_size <a5|a4|a3>`: The paper size of the PDF.
  * `--notation_type <figurine|algebraic>`: The chess notation style.
  * `--display_boards`: Show board diagrams for the moves.
  * `--board_scope <all|smart>`: Display boards for all moves or only for moves with errors.
  * `--how_to_read`: Include a "How to Read This Book" section with explanations.
  * `--book_design_dir <dir>`: A directory with files for the cover, dedication, etc.

### **Example**

This command will generate a complete A5-sized book in French with all features enabled:

```shell
python generate_chess_book.py top_5_quality.pgn output --book_design_dir input --title "Krystof126" --subtitle "Ses plus belles parties d'échecs" --author "Pascal GILLET" --notation_type figurine --display_boards --board_scope all --language fr --paper_size a5 --how_to_read
```
