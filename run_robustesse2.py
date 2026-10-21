"""
Robustesse, suite (modèle CV).
 C) n = 12 : 5 instances (graines d'instance 1 à 5), ALNS (graine 1 et meilleure des 5 graines) contre exact (90 s).
 D) n = 15 et 20 : 5 instances, ALNS seul (5 graines), car l'exact ne trouve plus de solution.
Résultats : robustesse_C.jsonl, robustesse_D.jsonl
"""
import json
import time
from alns_solver import alns
from scip_solver import build_and_solve_scip
from instance_generator import generate_instance, arc_cost_generic
from ortools.linear_solver import pywraplp

acf = lambda data, i, j: arc_cost_generic(data, i, j)


def find_k(data, k_start, k_max):
    for k in range(k_start, k_max + 1):
        _, c, s = alns(data, n_vehicles=k, arc_cost_fn=acf, max_iter=300, seed=1)
        if s == "OK":
            return k
    return None


# ---------------- C : n = 12, ALNS contre exact ----------------
with open("robustesse_C.jsonl", "w") as out:
    n = 12
    for iseed in range(1, 6):
        data = generate_instance(n, seed=iseed)
        k = find_k(data, 5, n)
        row = {"n": n, "instance": iseed, "K": k}
        if k is not None:
            costs, times = [], []
            for seed in range(1, 6):
                t0 = time.time()
                _, c, s = alns(data, n_vehicles=k, arc_cost_fn=acf, max_iter=300, seed=seed)
                costs.append(c if s == "OK" else None)
                times.append(time.time() - t0)
            row.update({"alns_seed1": costs[0], "alns_best5": min(x for x in costs if x), "alns_costs": costs, "alns_time1": times[0]})
            t1 = time.time()
            solver, st, _ = build_and_solve_scip(data, k, ev=False, time_limit_s=90)
            row["exact_time"] = time.time() - t1
            row["exact_status"] = {pywraplp.Solver.OPTIMAL: "OPTIMAL", pywraplp.Solver.FEASIBLE: "FEASIBLE"}.get(st, "AUCUNE")
            row["exact_ub"] = solver.Objective().Value() if st in (0, 1) else None
        out.write(json.dumps(row) + "\n"); out.flush()
        print("C", row, flush=True)

# ---------------- D : n = 15 et 20, ALNS seul ----------------
with open("robustesse_D.jsonl", "w") as out:
    for n, kref in [(15, 9), (20, 12)]:
        for iseed in range(1, 6):
            data = generate_instance(n, seed=iseed)
            k = find_k(data, kref - 1, kref + 3)
            row = {"n": n, "instance": iseed, "K": k}
            if k is not None:
                costs, times = [], []
                for seed in range(1, 6):
                    t0 = time.time()
                    _, c, s = alns(data, n_vehicles=k, arc_cost_fn=acf, max_iter=300, seed=seed)
                    costs.append(c if s == "OK" else None)
                    times.append(time.time() - t0)
                row.update({"alns_costs": costs, "alns_time_mean": sum(times) / len(times)})
            out.write(json.dumps(row) + "\n"); out.flush()
            print("D", row, flush=True)
print("TERMINE", flush=True)
