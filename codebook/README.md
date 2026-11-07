# Bot Codebook

> Japanese version: [README.ja.md](README.ja.md)

`bot_codebook.csv` hand-codes the engine family of the 80 bots that played the most rated games against humans in August 2026. Together they account for about 96% of human-vs-bot games. Each code is based on the bot's Lichess profile (bio and real name), and the `basis` column records the evidence. When a bot appears here, its code overrides the keyword classifier in `bots.classify_engine`.

| Family | Definition | Group used in analyses |
|---|---|---|
| `maia` | Maia networks (official maia1/5/9, maia3 models, Maia-weight bots such as Humaia) | humanlike |
| `humanlike` | Other bots trained on, or explicitly designed to imitate, human play (e.g. dala, human error models) | humanlike |
| `stockfish` | Stockfish or Fairy-Stockfish, possibly at reduced levels | engine |
| `leela` | Lc0/Leela networks used as a conventional engine | engine |
| `homemade` | Other search engines, own or third-party (e.g. Lynx, Demolito, GarboChess) | engine |
| `retro` | Re-implementations of historical or minimal engines at shallow depth (SARGON, TUROCHAMP, Bernstein, 3615 DIAGO, μSunfish) | engine |
| `weak_novelty` | Gimmick or deliberately handicapped bots (random movers, trick or queen-sacrifice bots, "loses Elo per check") | other |
| `unknown` | Bio does not state the engine | other |

Coding rules:
1. A bot's *declared method* decides its family. Its name alone does not, except for an explicit `maia` name.
2. A gimmick that defines the bot's play overrides the underlying engine. For example, LeelaJester is coded `weak_novelty`, not `leela`.
3. "Human-like" requires a stated imitation mechanism (trained on human games or a human error model) or an explicit claim to play like humans. Merely being weak does not qualify.
