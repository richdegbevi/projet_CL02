"""
Tests de robustesse (modèle CV).
 A) Variabilité de l'ALNS : 5 graines de l'ALNS sur la même instance (graine d'instance 42).
 B) 5 instances différentes par taille (graines d'instance 1 à 5), ALNS contre exact au même K.
Résultats : robustesse_A.jsonl et robustesse_B.jsonl
"""
import json
import time
from alns_solver import alns
from scip_solver import build_and_solve_scip
from instance_generator import generate_instance, arc_cost_generic
from ortools.linear_solver import pywraplp

acf = lambda data, i, j: arc_cost_generic(data, i, j)

# ---------------- A : variabilité de l'ALNS ----------------
with open("robustesse_A.jsonl", "w") as out:
    for n, k in [(10, 7), (15, 9), (20, 12)]:
        data = generate_instance(n, seed=42)
        costs, times = [], []
        for seed in range(1, 6):
            t0 = time.time()
            _, c, s = alns(data, n_vehicles=k, arc_cost_fn=acf, max_iter=300, seed=seed)
            costs.append(c if s == "OK" else None)
            times.append(time.time() - t0)
        row = {"n": n, "K": k, "costs": costs, "times": times}
        out.write(json.dumps(row) + "\n"); out.flush()
        print("A", row, flush=True)

# ---------------- B : 5 instances par taille ----------------
with open("robustesse_B.jsonl", "w") as out:
    for n in (6, 8, 10):
        for iseed in range(1, 6):
            data = generate_instance(n, seed=iseed)
            kmin, cost_alns, t_alns = None, None, None
            for k in range(1, n + 1):
                t0 = time.time()
                _, c, s = alns(data, n_vehicles=k, arc_cost_fn=acf, max_iter=300, seed=1)
                if s == "OK":
                    kmin, cost_alns, t_alns = k, c, time.time() - t0
                    break
            row = {"n": n, "instance": iseed, "K": kmin, "alns_cost": cost_alns, "alns_time": t_alns}
            if kmin is not None:
                t1 = time.time()
                solver, st, _ = build_and_solve_scip(data, kmin, ev=False, time_limit_s=45)
                row["exact_time"] = time.time() - t1
                row["exact_status"] = {pywraplp.Solver.OPTIMAL: "OPTIMAL", pywraplp.Solver.FEASIBLE: "FEASIBLE"}.get(st, "AUCUNE")
                row["exact_ub"] = solver.Objective().Value() if st in (0, 1) else None
            out.write(json.dumps(row) + "\n"); out.flush()
            print("B", row, flush=True)
print("TERMINE", flush=True)
