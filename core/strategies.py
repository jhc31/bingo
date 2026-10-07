"""Number-picking strategies, all strictly walk-forward.

Every strategy returns a score matrix S of shape (T, 80): S[t] ranks the 80 numbers
for draw t using only draws 0..t-1. Higher score = picked first. Integer scores get a
small random jitter so ties are broken randomly instead of favouring low numbers.
"""
import numpy as np

N = 80


def draw_matrix(numbers: list[list[int]]) -> np.ndarray:
    """(T, 80) 0/1 matrix, D[t, j] = 1 if number j+1 was drawn in draw t."""
    D = np.zeros((len(numbers), N), dtype=np.int8)
    for t, nums in enumerate(numbers):
        D[t, np.asarray(nums) - 1] = 1
    return D


def window_counts(D: np.ndarray, w: int) -> np.ndarray:
    """C[t, j] = times number j appeared in draws t-w..t-1 (fewer at the very start)."""
    cs = np.vstack([np.zeros((1, N), dtype=np.int32), np.cumsum(D, axis=0, dtype=np.int32)])
    T = len(D)
    idx = np.arange(T)
    return (cs[idx] - cs[np.maximum(idx - w, 0)]).astype(np.int16)


def gaps(D: np.ndarray) -> np.ndarray:
    """G[t, j] = draws since number j last appeared before draw t (遺漏期數)."""
    T = len(D)
    G = np.zeros((T, N), dtype=np.int32)
    g = np.zeros(N, dtype=np.int32)
    for t in range(T):
        G[t] = g
        g += 1
        g[D[t] == 1] = 0
    return G


def follow_scores(D: np.ndarray) -> np.ndarray:
    """拖號: score_j = mean over i in last draw of P(j drawn | i drawn in the previous draw),
    estimated from all earlier consecutive draw pairs."""
    T = len(D)
    F = np.zeros((T, N), dtype=np.float32)
    pair = np.zeros((N, N), dtype=np.float64)   # pair[i, j]: i at t-1 and j at t
    seen = np.zeros(N, dtype=np.float64)        # times i appeared with a following draw
    Df = D.astype(np.float64)
    for t in range(2, T):
        prev, cur = Df[t - 2], Df[t - 1]
        pair += np.outer(prev, cur)
        seen += prev
        last = cur.astype(bool)
        F[t] = (pair[last] / np.maximum(seen[last], 1)[:, None]).mean(axis=0)
    return F


def logistic_scores(D, feats: np.ndarray, start: int, train_len=20000, refit_every=10000, iters=8):
    """Per-number logistic regression on hand-made features, refit periodically on the
    most recent `train_len` draws (Newton/IRLS). Rows before `start` are left at 0."""
    T, _, k = feats.shape
    S = np.zeros((T, N), dtype=np.float32)
    coefs = []
    for t0 in range(start, T, refit_every):
        X = feats[t0 - train_len:t0].reshape(-1, k).astype(np.float64)
        X = np.hstack([np.ones((len(X), 1)), X])
        y = D[t0 - train_len:t0].reshape(-1).astype(np.float64)
        beta = np.zeros(X.shape[1])
        beta[0] = np.log(0.25 / 0.75)
        for _ in range(iters):
            p = 1 / (1 + np.exp(-X @ beta))
            grad = X.T @ (y - p)
            H = (X * (p * (1 - p))[:, None]).T @ X + 1e-6 * np.eye(len(beta))
            beta += np.linalg.solve(H, grad)
        coefs.append(beta)
        t1 = min(t0 + refit_every, T)
        Xs = feats[t0:t1].astype(np.float64)
        S[t0:t1] = (Xs @ beta[1:] + beta[0]).astype(np.float32)
    return S, coefs


DESCRIPTIONS = {
    "random": "隨機選號（對照組）",
    "fixed": "固定號碼（每期同一組）",
    "hot_10": "熱號：近10期出現最多",
    "hot_50": "熱號：近50期出現最多",
    "hot_200": "熱號：近200期出現最多",
    "hot_1000": "熱號：近1000期出現最多",
    "cold_50": "冷號：近50期出現最少",
    "cold_200": "冷號：近200期出現最少",
    "cold_1000": "冷號：近1000期出現最少",
    "overdue": "遺漏：最久沒開的號碼",
    "repeat": "連莊：上期號碼中近100期最熱",
    "follow": "拖號：上期號碼的下期跟隨機率",
    "logit": "機器學習：Logistic 綜合以上特徵",
}


def build_strategies(D: np.ndarray, start: int, seed: int = 2026, logit_train_len: int = 20000) -> dict:
    """Return {strategy name: (description, score matrix)}. The logistic model is first fit
    at row `start` on the preceding `logit_train_len` draws."""
    rng = np.random.default_rng(seed)
    T = len(D)
    jitter = lambda: rng.random((T, N), dtype=np.float32) * 0.5  # noqa: E731

    cnt = {w: window_counts(D, w) for w in (10, 50, 100, 200, 1000)}
    G = gaps(D)
    F = follow_scores(D)

    fixed = np.zeros((T, N), dtype=np.float32)
    # One random ranking chosen once (constant seed) and reused for every draw.
    fixed[:, np.random.default_rng(80).permutation(N)] = np.arange(N, 0, -1, dtype=np.float32)

    s = {
        "random": rng.random((T, N), dtype=np.float32),
        "fixed": fixed,
        "hot_10": cnt[10] + jitter(),
        "hot_50": cnt[50] + jitter(),
        "hot_200": cnt[200] + jitter(),
        "hot_1000": cnt[1000] + jitter(),
        "cold_50": -cnt[50] + jitter(),
        "cold_200": -cnt[200] + jitter(),
        "cold_1000": -cnt[1000] + jitter(),
        "overdue": G + jitter(),
        "repeat": D[np.maximum(np.arange(T) - 1, 0)].astype(np.float32) * 1000 + cnt[100] + jitter(),
        "follow": F,
    }

    # Logistic regression on the same signals combined.
    last = np.vstack([np.zeros((1, N), dtype=np.int8), D[:-1]])
    feats = np.stack([
        cnt[10] / 10, cnt[50] / 50, cnt[200] / 200, cnt[1000] / 1000,
        np.log1p(G), last, (F - 0.25) * 10,
    ], axis=2).astype(np.float32)
    L, _ = logistic_scores(D, feats, start, train_len=logit_train_len)
    s["logit"] = L
    return {name: (DESCRIPTIONS[name], S) for name, S in s.items()}


def predict_next(history: list[list[int]], seed: int, top: int = 10, logit_train_len: int = 10000) -> dict:
    """Rank numbers for the draw right after `history` (oldest first) with every strategy.

    A blank row is appended for the upcoming draw; every score at that row only uses
    earlier rows, exactly as in the backtest. Returns {name: (description, top picks)}.
    """
    D = np.vstack([draw_matrix(history), np.zeros((1, N), dtype=np.int8)])
    T = len(D)
    train_len = min(logit_train_len, T - 1 - 1000)
    out = {}
    for name, (desc, S) in build_strategies(D, T - 1, seed=seed, logit_train_len=train_len).items():
        out[name] = (desc, [int(i) + 1 for i in np.argsort(-S[-1])[:top]])
    return out
