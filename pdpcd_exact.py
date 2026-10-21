"""
Modèle exact (MILP) du PDPCD - modèle de base (véhicules conventionnels),
suivant fidèlement Gkiotsalitis & Nikolopoulou (2023), équations (1)-(24).

C'est le même modèle de base réutilisé dans l'article principal du projet
(Nisyrios, Dimopoulos & Gkiotsalitis, 2026), avant l'extension VE.
"""
import gurobipy as gp
from gurobipy import GRB
import instance_n4 as inst


def build_and_solve(verbose=True):
    P, D, K = inst.P, inst.D, inst.K
    n = inst.n
    O = ["o1", "o2", "o3", "o4"]
    V = O + P + D

    # --- ensemble des arcs faisables A (définition formelle de l'article) --
    A = []
    A += [("o1", j) for j in P]
    A += [(i, j) for i in P for j in P if i != j]
    A += [(i, "o2") for i in P]
    A += [("o3", j) for j in D]
    A += [(i, j) for i in D for j in D if i != j]
    A += [(i, "o4") for i in D]

    c = {(i, j): inst.arc_cost(i, j) for (i, j) in A}

    m = gp.Model("PDPCD_base")
    if not verbose:
        m.Params.OutputFlag = 0

    # --- variables ---------------------------------------------------
    x = m.addVars(((k, i, j) for k in K for (i, j) in A), vtype=GRB.BINARY, name="x")
    u = m.addVars(((k, i) for k in K for i in V), lb=0.0, name="u")
    r = m.addVars(P, lb=0.0, name="r")
    eta = m.addVars(((k, i) for k in K for i in P), vtype=GRB.BINARY, name="eta")
    theta = m.addVars(((k, i) for k in K for i in P), vtype=GRB.BINARY, name="theta")
    eta_k = m.addVars(K, vtype=GRB.BINARY, name="eta_k")     # eta~^k
    theta_k = m.addVars(K, vtype=GRB.BINARY, name="theta_k")  # theta~^k
    tau = m.addVars(K, lb=0.0, name="tau")
    w = m.addVars(K, lb=0.0, name="w")
    z = m.addVars(P, lb=0.0, name="z")
    # linéarisation (23)-(24)
    utilde = m.addVars(V, lb=0.0, name="utilde")
    sigma = m.addVars(((k, i, j) for k in K for (i, j) in A), lb=-GRB.INFINITY, name="sigma")

    M = inst.M

    # --- (1) fonction objectif ------------------------------------------
    m.setObjective(gp.quicksum(c[i, j] * x[k, i, j] for k in K for (i, j) in A),
                   GRB.MINIMIZE)

    # --- (2) chaque sommet de demande visité exactement une fois -------
    for i in P + D:
        m.addConstr(gp.quicksum(x[k, i, j] for k in K for j in V if (i, j) in c) == 1,
                    name=f"visit_{i}")

    # --- (3),(4) capacité du véhicule --------------------------------
    for k in K:
        m.addConstr(gp.quicksum(inst.q[i] * x[k, i, j] for i in P for j in V if (i, j) in c)
                    <= inst.Q[k], name=f"capP_{k}")
        m.addConstr(gp.quicksum(inst.q[i] * x[k, i, j] for i in D for j in V if (i, j) in c)
                    <= inst.Q[k], name=f"capD_{k}")

    # --- (5) toute route de collecte commence en o1, livraison commence en o3 ---
    for k in K:
        m.addConstr(gp.quicksum(x[k, "o1", j] for j in P) == 1, name=f"start_o1_{k}")
        m.addConstr(gp.quicksum(x[k, "o3", j] for j in D) == 1, name=f"start_o3_{k}")

    # --- (6) toute route de collecte se termine en o2, livraison en o4 -
    for k in K:
        m.addConstr(gp.quicksum(x[k, j, "o2"] for j in P) == 1, name=f"end_o2_{k}")
        m.addConstr(gp.quicksum(x[k, j, "o4"] for j in D) == 1, name=f"end_o4_{k}")

    # --- (7) conservation de flux -------------------------------------
    for k in K:
        for h in P + D:
            inflow = gp.quicksum(x[k, i, h] for i in V if (i, h) in c)
            outflow = gp.quicksum(x[k, h, j] for j in V if (h, j) in c)
            m.addConstr(inflow - outflow == 0, name=f"flow_{k}_{h}")

    # --- (8) séquencement temporel -----------------------------------
    for k in K:
        for (i, j) in A:
            m.addConstr(u[k, j] >= u[k, i] + c[i, j] - M * (1 - x[k, i, j]),
                        name=f"seq_{k}_{i}_{j}")

    # --- (9) fenêtres de temps ------------------------------------------
    for k in K:
        for i in P + D:
            e_i, l_i = inst.tw[i]
            m.addConstr(u[k, i] >= e_i, name=f"tw_lo_{k}_{i}")
            m.addConstr(u[k, i] <= l_i, name=f"tw_hi_{k}_{i}")
        m.addConstr(u[k, "o1"] >= inst.e_o1, name=f"tw_o1_lo_{k}")
        m.addConstr(u[k, "o4"] <= inst.l_o4, name=f"tw_o4_hi_{k}")

    # --- (10),(11) statut de déchargement/rechargement par demande ---------------
    for k in K:
        for i in P:
            rhs = (gp.quicksum(x[k, i, j] for j in (P + ["o2"]) if j != i and (i, j) in c)
                   - gp.quicksum(x[k, i + n, j] for j in (D + ["o4"]) if j != i + n and (i + n, j) in c))
            m.addConstr(eta[k, i] - theta[k, i] == rhs, name=f"etatheta_{k}_{i}")
            m.addConstr(eta[k, i] + theta[k, i] <= 1, name=f"etatheta_le1_{k}_{i}")

    # --- (12),(13) eta~^k / theta~^k -----------------------------------
    for k in K:
        s_eta = gp.quicksum(eta[k, i] for i in P)
        s_theta = gp.quicksum(theta[k, i] for i in P)
        m.addConstr((1 / M) * s_eta <= eta_k[k], name=f"etak_lo_{k}")
        m.addConstr(eta_k[k] <= s_eta, name=f"etak_hi_{k}")
        m.addConstr((1 / M) * s_theta <= theta_k[k], name=f"thetak_lo_{k}")
        m.addConstr(theta_k[k] <= s_theta, name=f"thetak_hi_{k}")

    # --- (14)-(18) synchronisation au crossdock --------------------------
    for k in K:
        m.addConstr(tau[k] == u[k, "o2"] + inst.a * eta_k[k]
                    + inst.beta * gp.quicksum(inst.q[i] * eta[k, i] for i in P),
                    name=f"tau_{k}")
        m.addConstr(w[k] >= tau[k], name=f"w_ge_tau_{k}")
        m.addConstr(u[k, "o3"] == w[k] + inst.a * theta_k[k]
                    + inst.beta * gp.quicksum(inst.q[i] * theta[k, i] for i in P),
                    name=f"uo3_{k}")
        for i in P:
            m.addConstr(w[k] >= z[i] - M * (1 - theta[k, i]), name=f"w_z_{k}_{i}")
            m.addConstr(z[i] >= tau[k] - M * (1 - eta[k, i]), name=f"z_tau_{k}_{i}")

    # --- (19),(20) durée maximale de la route ------------------------------
    for k in K:
        m.addConstr(u[k, "o2"] - u[k, "o1"] <= inst.T[k], name=f"dur_pick_{k}")
        m.addConstr(u[k, "o4"] - u[k, "o3"] <= inst.T[k], name=f"dur_deliv_{k}")

    # --- (23)-(24) linéarisation du ride time ---------------------------
    for k in K:
        for (i, j) in A:
            if j in (P + D):
                m.addConstr(utilde[j] + sigma[k, i, j] == u[k, j], name=f"lin_eq_{k}_{i}_{j}")
                m.addConstr(sigma[k, i, j] <= M * (1 - x[k, i, j]), name=f"lin_up_{k}_{i}_{j}")
                m.addConstr(sigma[k, i, j] >= -M * (1 - x[k, i, j]), name=f"lin_lo_{k}_{i}_{j}")
    for i in P:
        m.addConstr(r[i] == utilde[i + n] - utilde[i], name=f"ridetime_{i}")
        m.addConstr(r[i] <= inst.L, name=f"ridetime_max_{i}")

    m.optimize()

    return m, x, u, r


if __name__ == "__main__":
    m, x, u, r = build_and_solve(verbose=True)
    print("\n=== RÉSULTAT ===")
    print(f"Statut : {m.Status} (2 = optimal)")
    print(f"Coût total (doit correspondre à 1101.234) : {m.ObjVal:.3f}")
    print(f"Nb. de contraintes (CNS, doit correspondre à 1091) : {m.NumConstrs}")
    print(f"Nœuds explorés (NE, l'article rapporte 1) : {m.NodeCount}")
