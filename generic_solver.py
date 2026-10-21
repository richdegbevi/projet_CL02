"""
Solveur générique (CV et EV) paramétré par instance et par nombre de
véhicules, avec recherche automatique de la taille de flotte minimale
faisable -- pour reproduire, à notre échelle, l'analyse "combien de
véhicules faut-il ?" faite dans l'article principal (Tableau 5/13).
"""
import gurobipy as gp
from gurobipy import GRB
from instance_generator import arc_cost_generic


def build_and_solve_generic(data, n_vehicles, ev=False,
                             e_rate=0.2, soc_max=120.0, v_charge=150.0,
                             time_limit=60, verbose=False):
    P, D = data["P"], data["D"]
    n = data["n"]
    K = list(range(1, n_vehicles + 1))
    O = ["o1", "o2", "o3", "o4"]
    V = O + P + D
    soc_min = 0.1 * soc_max

    A = []
    A += [("o1", j) for j in P]
    A += [(i, j) for i in P for j in P if i != j]
    A += [(i, "o2") for i in P]
    A += [("o3", j) for j in D]
    A += [(i, j) for i in D for j in D if i != j]
    A += [(i, "o4") for i in D]

    c = {(i, j): arc_cost_generic(data, i, j) for (i, j) in A}
    M = data["M"]

    m = gp.Model("PDPCD_generic")
    m.Params.OutputFlag = 1 if verbose else 0
    m.Params.TimeLimit = time_limit

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
    if ev:
        soc_a = m.addVars(K, lb=0.0, name="SoC_a")
        soc_b = m.addVars(K, lb=0.0, name="SoC_b")
        cdt = m.addVars(K, lb=0.0, name="CDt")

    m.setObjective(gp.quicksum(c[i, j] * x[k, i, j] for k in K for (i, j) in A), GRB.MINIMIZE)

    for i in P + D:
        m.addConstr(gp.quicksum(x[k, i, j] for k in K for j in V if (i, j) in c) == 1)
    for k in K:
        m.addConstr(gp.quicksum(data["q"][i] * x[k, i, j] for i in P for j in V if (i, j) in c) <= data["Q"])
        m.addConstr(gp.quicksum(data["q"][i] * x[k, i, j] for i in D for j in V if (i, j) in c) <= data["Q"])
        m.addConstr(gp.quicksum(x[k, "o1", j] for j in P) == 1)
        m.addConstr(gp.quicksum(x[k, "o3", j] for j in D) == 1)
        m.addConstr(gp.quicksum(x[k, j, "o2"] for j in P) == 1)
        m.addConstr(gp.quicksum(x[k, j, "o4"] for j in D) == 1)
        for h in P + D:
            inflow = gp.quicksum(x[k, i, h] for i in V if (i, h) in c)
            outflow = gp.quicksum(x[k, h, j] for j in V if (h, j) in c)
            m.addConstr(inflow - outflow == 0)
        for (i, j) in A:
            m.addConstr(u[k, j] >= u[k, i] + c[i, j] - M * (1 - x[k, i, j]))
        for i in P + D:
            e_i, l_i = data["tw"][i]
            m.addConstr(u[k, i] >= e_i)
            m.addConstr(u[k, i] <= l_i)
        m.addConstr(u[k, "o1"] >= data["e_o1"])
        m.addConstr(u[k, "o4"] <= data["l_o4"])
        for i in P:
            rhs = (gp.quicksum(x[k, i, j] for j in (P + ["o2"]) if j != i and (i, j) in c)
                   - gp.quicksum(x[k, i + n, j] for j in (D + ["o4"]) if j != i + n and (i + n, j) in c))
            m.addConstr(eta[k, i] - theta[k, i] == rhs)
            m.addConstr(eta[k, i] + theta[k, i] <= 1)
        s_eta = gp.quicksum(eta[k, i] for i in P)
        s_theta = gp.quicksum(theta[k, i] for i in P)
        m.addConstr((1 / M) * s_eta <= eta_k[k])
        m.addConstr(eta_k[k] <= s_eta)
        m.addConstr((1 / M) * s_theta <= theta_k[k])
        m.addConstr(theta_k[k] <= s_theta)
        m.addConstr(tau[k] == u[k, "o2"] + data["a"] * eta_k[k]
                    + data["beta"] * gp.quicksum(data["q"][i] * eta[k, i] for i in P))
        m.addConstr(w[k] >= tau[k])
        m.addConstr(u[k, "o3"] == w[k] + data["a"] * theta_k[k]
                    + data["beta"] * gp.quicksum(data["q"][i] * theta[k, i] for i in P))
        for i in P:
            m.addConstr(w[k] >= z[i] - M * (1 - theta[k, i]))
            m.addConstr(z[i] >= tau[k] - M * (1 - eta[k, i]))
        m.addConstr(u[k, "o2"] - u[k, "o1"] <= data["T"])
        m.addConstr(u[k, "o4"] - u[k, "o3"] <= data["T"])
        for (i, j) in A:
            if j in (P + D):
                m.addConstr(utilde[j] + sigma[k, i, j] == u[k, j])
                m.addConstr(sigma[k, i, j] <= M * (1 - x[k, i, j]))
                m.addConstr(sigma[k, i, j] >= -M * (1 - x[k, i, j]))
        if ev:
            # énergie sur TOUS les arcs de la phase (y compris o1->1er arrêt, o3->1er arrêt)
            pickup_energy = gp.quicksum(c[i, j] * x[k, i, j] * e_rate for i in ["o1"] + P for j in V if (i, j) in c)
            delivery_energy = gp.quicksum(c[i, j] * x[k, i, j] * e_rate for i in ["o3"] + D for j in V if (i, j) in c)
            m.addConstr(pickup_energy <= soc_max - soc_min)
            m.addConstr(soc_a[k] == soc_max - pickup_energy)
            m.addConstr(cdt[k] == data["a"] * eta_k[k] + data["beta"] * gp.quicksum(data["q"][i] * eta[k, i] for i in P)
                        + data["a"] * theta_k[k] + data["beta"] * gp.quicksum(data["q"][i] * theta[k, i] for i in P))
            # v en kW, CDt en secondes -> kWh = v * CDt / 3600
            m.addConstr(soc_b[k] == v_charge * cdt[k] / 3600.0 + soc_a[k])
            m.addConstr(soc_b[k] <= soc_max)
            m.addConstr(delivery_energy <= soc_b[k] - soc_min)

    for i in P:
        m.addConstr(r[i] == utilde[i + n] - utilde[i])
        m.addConstr(r[i] <= data["L"])

    m.optimize()
    return m


def find_min_fleet(data, ev, k_start=2, k_max=6, time_limit=60):
    """Augmente n_vehicles jusqu'à trouver une solution faisable (ou dépasser k_max)."""
    for k in range(k_start, k_max + 1):
        m = build_and_solve_generic(data, k, ev=ev, time_limit=time_limit)
        if m.Status == GRB.OPTIMAL:
            return k, m.ObjVal, m.NumConstrs, m.NodeCount, m.Runtime, "OPTIMAL"
        elif m.Status == GRB.TIME_LIMIT and m.SolCount > 0:
            return k, m.ObjVal, m.NumConstrs, m.NodeCount, m.Runtime, f"TIME_LIMIT(gap={m.MIPGap:.2%})"
        # infactível ou sem solução -> tenta com mais um veículo
    return None, None, None, None, None, "INFEASIBLE_UP_TO_KMAX"
