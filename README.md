# Chess Book Generator ♟️

This project provides a complete toolchain to fetch your chess games from Chess.com, analyze and select the best ones, and compile them into a beautifully formatted, print-ready PDF book.

The process is broken down into three main steps:

1.  **Fetch Games**: Download all your games from Chess.com.
2.  **Analyze & Select**: Analyze every game, calculate quality metrics, and select the top games based on your criteria.
3.  **Generate Book**: Compile the selected games into a professional PDF.

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

This step uses the `select_top_games.py` script to analyze the PGN file from Step 1, calculate metrics like average centipawn loss and a quality score for each game, and store everything in a SQLite database. Once the database is built, you can export the top games based on various criteria.

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
    
  * **To get the 15 lowest CPL games, sorted by date**

    ```shell
    python select_top_games.py export analysis.db top_15_low_cpl.pgn -n 15 --sort_by avg_cpl:asc game_datetime:asc
    ```

This will generate a smaller, curated PGN file (e.g., `top_5_quality.pgn`) that you will use in the final step.

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
