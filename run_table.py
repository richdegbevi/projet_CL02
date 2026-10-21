"""
Tableau exact / ALNS pour n = 1 à 20 (modèle de base, véhicules conventionnels).
Pour chaque n : ALNS à K fixé (temps d'une seule exécution), puis modèle exact
(SCIP via OR-Tools) au même K.
Résultats écrits ligne par ligne dans results_table.jsonl.
"""
import json
import sys
import time
from alns_solver import alns
from scip_solver import build_and_solve_scip
from instance_generator import generate_instance, arc_cost_generic
from ortools.linear_solver import pywraplp


K_OF_N = {1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 4, 7: 6, 8: 6, 9: 6, 10: 7,
          11: 6, 12: 8, 13: 8, 14: 9, 15: 9, 16: 9, 17: 10, 18: 12, 19: 12, 20: 12}


def acf(data, i, j):
    return arc_cost_generic(data, i, j)


START = int(sys.argv[1]) if len(sys.argv) > 1 else 1
with open("results_table.jsonl", "a" if START > 1 else "w") as out:
    for n, k in K_OF_N.items():
        if n < START:
            continue
        data = generate_instance(n, seed=42)

        t0 = time.time()
        _, cost_alns, status_alns = alns(data, n_vehicles=k, arc_cost_fn=acf, max_iter=300, seed=1)
        t_alns = time.time() - t0

        limit = 60 if n <= 9 else 90
        t1 = time.time()
        solver, status, _ = build_and_solve_scip(data, k, ev=False, time_limit_s=limit)
        t_exact = time.time() - t1

        row = {"n": n, "K": k,
               "alns_cost": cost_alns if status_alns == "OK" else None, "alns_time": t_alns,
               "exact_status": {pywraplp.Solver.OPTIMAL: "OPTIMAL",
                                pywraplp.Solver.FEASIBLE: "FEASIBLE"}.get(status, f"AUCUNE({status})"),
               "exact_time": t_exact, "limit": limit}
        obj = solver.Objective()
        row["exact_ub"] = obj.Value() if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE) else None
        out.write(json.dumps(row) + "\n")
        out.flush()
        print(row, flush=True)
