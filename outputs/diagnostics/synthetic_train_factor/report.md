# Synthetic recovery of a per-train factor w_k (phase C; synthetic only, config.json holds the declared rules/hashes)
Files: step0_identifiability.json, results.csv, progress.json, config.json.
Verdict by the declared rules (E2, 2% noise): FAILURE. E2 within-hour corr: a 0.006, b -0.041, d 0.129 (all < 0.5). Null scenario c: std(w_hat)/mean 1.9 (rule <= 0.05) -> fails, the method invents patterns.
E1 (pi known, exact data) recovers w (within-hour corr 0.99 / 0.89 / 0.81 for a / b / d) but collapses at 2% noise (0.23 / 0.28 / 0.32) and the null control gives std 0.59 at 2%. E3 (shared kernel, exploratory) 0.60 for the smooth rush at both noise levels, 0.0-0.2 elsewhere. Step 0: rank 195 of 242 (fixed beta, pi), 194 with beta profiled; predicted recoverable within-hour variance 0.4-0.74 (fixed) and 0.24-0.55 (profiled).
Limits: unregularized max-likelihood; maxiter reached (not converged) in most fits; one date, one seed; kernel in E3 matches truth family.
