"""
Extension du modèle de base (PDPCD) aux véhicules électriques : PDPCDEVs.
Ajoute les équations (28)-(32) de l'article principal (Nisyrios, Dimopoulos &
Gkiotsalitis, 2026) par-dessus le modèle déjà validé dans pdpcd_exact.py.

Paramètres VE utilisés dans l'article principal pour le réseau-jouet (Fig. 2,
même réseau réutilisé ici) : e=0.2 kWh/km, SoC_max=120 kWh,
SoC_min = 0.1*SoC_max = 12 kWh, v=150 kW.
"""
import gurobipy as gp
from gurobipy import GRB
import instance_n4 as inst

# --- paramètres VE (article principal, section 4.1) --------------------------
E_RATE = 0.2      # kWh/km (ici on traite "km" == unité de tij, comme le fait l'article)
SOC_MAX = 120.0
SOC_MIN = 0.1 * SOC_MAX   # 12.0
V_CHARGE = 150.0  # kW
SECONDES_PAR_HEURE = 3600.0   # le temps des instances est en secondes


def build_and_solve_ev(verbose=True):
    P, D, K = inst.P, inst.D, inst.K
    n = inst.n
    O = ["o1", "o2", "o3", "o4"]
    V = O + P + D

    A = []
    A += [("o1", j) for j in P]
    A += [(i, j) for i in P for j in P if i != j]
    A += [(i, "o2") for i in P]
    A += [("o3", j) for j in D]
    A += [(i, j) for i in D for j in D if i != j]
    A += [(i, "o4") for i in D]

    c = {(i, j): inst.arc_cost(i, j) for (i, j) in A}
    # distance = même valeur que le coût/temps (l'article ne sépare pas d_ij de
    # t_ij pour cette instance ; les deux dérivent de la même matrice d'arcs)
    d = c

    m = gp.Model("PDPCDEVs")
    if not verbose:
        m.Params.OutputFlag = 0

    x = m.addVars(((k, i, j) for k in K for (i, j) in A), vtype=GRB.BINARY, name="x")
    u = m.addVars(((k, i) for k in K for i in V), lb=0.0, name="u")
    r = m.addVars(P, lb=0.0, name="r")
    eta = m.addVars(((k, i) for k in K for i in P), vtype=GRB.BINARY, name="eta")
    theta = m.addVars(((k, i) for k in K for i in P), vtype=GRB.BINARY, name="theta")
    eta_k = m.addVars(K, vtype=GRB.BINARY, name="eta_k")
    theta_k = m.addVars(K, vtype=GRB.BINARY, name="theta_k")
    tau = m.addVars(K, lb=0.0, name="tau")
    w = m.addVars(K, lb=0.0, name="w")
    z = m.addVars(P, lb=0.0, name="z")
    utilde = m.addVars(V, lb=0.0, name="utilde")
    sigma = m.addVars(((k, i, j) for k in K for (i, j) in A), lb=-GRB.INFINITY, name="sigma")

    # --- nouvelles variables du modèle VE (3.2.2) ---------------------------
    soc_a = m.addVars(K, lb=0.0, name="SoC_a")   # SoC à l'arrivée au crossdock
    soc_b = m.addVars(K, lb=0.0, name="SoC_b")   # SoC au départ du crossdock
    cdt = m.addVars(K, lb=0.0, name="CDt")       # temps disponible pour la recharge

    M = inst.M

    m.setObjective(gp.quicksum(c[i, j] * x[k, i, j] for k in K for (i, j) in A),
                   GRB.MINIMIZE)

    for i in P + D:
        m.addConstr(gp.quicksum(x[k, i, j] for k in K for j in V if (i, j) in c) == 1)

    for k in K:
        m.addConstr(gp.quicksum(inst.q[i] * x[k, i, j] for i in P for j in V if (i, j) in c)
                    <= inst.Q[k])
        m.addConstr(gp.quicksum(inst.q[i] * x[k, i, j] for i in D for j in V if (i, j) in c)
                    <= inst.Q[k])

    for k in K:
        m.addConstr(gp.quicksum(x[k, "o1", j] for j in P) == 1)
        m.addConstr(gp.quicksum(x[k, "o3", j] for j in D) == 1)
        m.addConstr(gp.quicksum(x[k, j, "o2"] for j in P) == 1)
        m.addConstr(gp.quicksum(x[k, j, "o4"] for j in D) == 1)

    for k in K:
        for h in P + D:
            inflow = gp.quicksum(x[k, i, h] for i in V if (i, h) in c)
            outflow = gp.quicksum(x[k, h, j] for j in V if (h, j) in c)
            m.addConstr(inflow - outflow == 0)

    for k in K:
        for (i, j) in A:
            m.addConstr(u[k, j] >= u[k, i] + c[i, j] - M * (1 - x[k, i, j]))

    for k in K:
        for i in P + D:
            e_i, l_i = inst.tw[i]
            m.addConstr(u[k, i] >= e_i)
            m.addConstr(u[k, i] <= l_i)
        m.addConstr(u[k, "o1"] >= inst.e_o1)
        m.addConstr(u[k, "o4"] <= inst.l_o4)

    for k in K:
        for i in P:
            rhs = (gp.quicksum(x[k, i, j] for j in (P + ["o2"]) if j != i and (i, j) in c)
                   - gp.quicksum(x[k, i + n, j] for j in (D + ["o4"]) if j != i + n and (i + n, j) in c))
            m.addConstr(eta[k, i] - theta[k, i] == rhs)
            m.addConstr(eta[k, i] + theta[k, i] <= 1)

    for k in K:
        s_eta = gp.quicksum(eta[k, i] for i in P)
        s_theta = gp.quicksum(theta[k, i] for i in P)
        m.addConstr((1 / M) * s_eta <= eta_k[k])
        m.addConstr(eta_k[k] <= s_eta)
        m.addConstr((1 / M) * s_theta <= theta_k[k])
        m.addConstr(theta_k[k] <= s_theta)

    for k in K:
        m.addConstr(tau[k] == u[k, "o2"] + inst.a * eta_k[k]
                    + inst.beta * gp.quicksum(inst.q[i] * eta[k, i] for i in P))
        m.addConstr(w[k] >= tau[k])
        m.addConstr(u[k, "o3"] == w[k] + inst.a * theta_k[k]
                    + inst.beta * gp.quicksum(inst.q[i] * theta[k, i] for i in P))
        for i in P:
            m.addConstr(w[k] >= z[i] - M * (1 - theta[k, i]))
            m.addConstr(z[i] >= tau[k] - M * (1 - eta[k, i]))

    for k in K:
        m.addConstr(u[k, "o2"] - u[k, "o1"] <= inst.T[k])
        m.addConstr(u[k, "o4"] - u[k, "o3"] <= inst.T[k])

    for k in K:
        for (i, j) in A:
            if j in (P + D):
                m.addConstr(utilde[j] + sigma[k, i, j] == u[k, j])
                m.addConstr(sigma[k, i, j] <= M * (1 - x[k, i, j]))
                m.addConstr(sigma[k, i, j] >= -M * (1 - x[k, i, j]))
    for i in P:
        m.addConstr(r[i] == utilde[i + n] - utilde[i])
        m.addConstr(r[i] <= inst.L)

    # --- (28)-(32) contraintes d'énergie (VE) ---------------------------
    for k in K:
        # CORRECTION : l'énergie porte sur TOUS les arcs de la phase, y compris
        # l'arc de départ du crossdock (o1 -> premier arrêt, o3 -> premier arrêt).
        # L'équation (28) imprimée somme sur i dans P seulement, mais les
        # résultats de l'article (Tableaux 4, 5 et 12) comptent la route entière.
        pickup_energy = gp.quicksum(d[i, j] * x[k, i, j] * E_RATE
                                     for i in ["o1"] + P for j in V if (i, j) in c)
        delivery_energy = gp.quicksum(d[i, j] * x[k, i, j] * E_RATE
                                       for i in ["o3"] + D for j in V if (i, j) in c)
        # (28) l'énergie de la phase de collecte tient dans la plage utilisable de la batterie
        m.addConstr(pickup_energy <= SOC_MAX - SOC_MIN, name=f"ev28_{k}")
        # (29) SoC à l'arrivée au crossdock
        m.addConstr(soc_a[k] == SOC_MAX - pickup_energy, name=f"ev29_{k}")
        # temps disponible de recharge au crossdock = temps total de manutention
        m.addConstr(cdt[k] == inst.a * eta_k[k]
                    + inst.beta * gp.quicksum(inst.q[i] * eta[k, i] for i in P)
                    + inst.a * theta_k[k]
                    + inst.beta * gp.quicksum(inst.q[i] * theta[k, i] for i in P),
                    name=f"cdt_{k}")
        # (30) SoC au départ du crossdock (après recharge opportuniste)
        # CORRECTION : conversion d'unités. v est en kW, CDt en secondes :
        # l'énergie rechargée (kWh) vaut v * CDt / 3600.
        m.addConstr(soc_b[k] == V_CHARGE * cdt[k] / SECONDES_PAR_HEURE + soc_a[k], name=f"ev30_{k}")
        # (31) ne peut pas dépasser la capacité maximale
        m.addConstr(soc_b[k] <= SOC_MAX, name=f"ev31_{k}")
        # (32) l'énergie de la phase de livraison doit tenir dans ce qui reste de batterie
        m.addConstr(delivery_energy <= soc_b[k] - SOC_MIN, name=f"ev32_{k}")

    m.optimize()
    return m, x, u, r, soc_a, soc_b


if __name__ == "__main__":
    m, x, u, r, soc_a, soc_b = build_and_solve_ev(verbose=False)
    print("=== MODÈLE VE (PDPCDEVs) - réseau de 4 demandes ===")
    if m.Status == GRB.OPTIMAL:
        print(f"Statut : OPTIMAL")
        print(f"Coût total : {m.ObjVal:.3f}")
        for k in inst.K:
            arcs_used = [(i, j) for (kk, i, j) in x.keys() if kk == k and x[kk, i, j].X > 0.5]
            print(f"Véhicule {k} : {arcs_used}  | SoC_a={soc_a[k].X:.2f}  SoC_b={soc_b[k].X:.2f}")
    else:
        print(f"Statut : {m.Status} (3 = INFEASIBLE) -- modèle infaisable avec {inst.K} véhicules")
