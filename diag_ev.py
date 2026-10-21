"""Diagnostic : la solution VE du modèle exact est-elle acceptée par l'évaluateur de l'ALNS ?"""
import sys
from scip_solver import build_and_solve_scip
from route_eval_alns import evaluate_full
from instance_generator import generate_instance, arc_cost_generic

EV = dict(e_rate=0.2, soc_max=120.0, v_charge=150.0)
acf = lambda data, i, j: arc_cost_generic(data, i, j)


def extract(x, n, K):
    """Reconstruit pickup/delivery (ordre de visite) à partir des variables x[k,i,j]."""
    nxt = {}
    for (k, i, j), var in x.items():
        if var.solution_value() > 0.5:
            nxt[(k, i)] = j
    pickup, delivery = {}, {}
    for k in range(1, K + 1):
        seq, cur = [], nxt[(k, "o1")]
        while cur != "o2":
            seq.append(cur)
            cur = nxt[(k, cur)]
        pickup[k] = seq
        seq, cur = [], nxt[(k, "o3")]
        while cur != "o4":
            seq.append(cur - n)       # on stocke l'identifiant de requête
            cur = nxt[(k, cur)]
        delivery[k] = seq
    return {"pickup": pickup, "delivery": delivery}


n, K = int(sys.argv[1]), int(sys.argv[2])
data = generate_instance(n, seed=42)
solver, st, x = build_and_solve_scip(data, K, ev=True, time_limit_s=40, **EV)
print("exact VE : statut", st, " coût", round(solver.Objective().Value(), 2))
sol = extract(x, n, K)
print("pickup  :", sol["pickup"])
print("delivery:", sol["delivery"])
for ev in (False, True):
    feas, cost, info = evaluate_full(data, sol, acf, ev=ev, **EV)
    print(f"évaluateur ALNS (ev={ev}) -> faisable={feas}  coût={cost if feas else '—'}  info={info if not feas else ''}")
