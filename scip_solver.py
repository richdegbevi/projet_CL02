"""
Même modèle (PDPCD base + extension EV) que generic_solver.py, mais
implémenté avec OR-Tools (backend SCIP) au lieu de Gurobi -- car la licence
gratuite de Gurobi est limitée à ~2000 lignes/colonnes, dépassée à partir de
n=7 demandes. SCIP est open-source, sans limite de taille, et un choix de
solveur tout à fait valable selon l'énoncé du projet ("Cplex, Gurobi, Gusek,
Lingo, Solveur Excel, Open Solver, etc.").
"""
from ortools.linear_solver import pywraplp
from instance_generator import arc_cost_generic


def build_and_solve_scip(data, n_vehicles, ev=False,
                          e_rate=0.2, soc_max=120.0, v_charge=150.0,
                          time_limit_s=120, verbose=False, valid_ineq=False):
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

    solver = pywraplp.Solver.CreateSolver("SCIP")
    solver.SetTimeLimit(time_limit_s * 1000)
    inf = solver.infinity()

    x = {(k, i, j): solver.BoolVar(f"x_{k}_{i}_{j}") for k in K for (i, j) in A}
    u = {(k, i): solver.NumVar(0, inf, f"u_{k}_{i}") for k in K for i in V}
    r = {i: solver.NumVar(0, inf, f"r_{i}") for i in P}
    eta = {(k, i): solver.BoolVar(f"eta_{k}_{i}") for k in K for i in P}
    theta = {(k, i): solver.BoolVar(f"theta_{k}_{i}") for k in K for i in P}
    eta_k = {k: solver.BoolVar(f"eta_k_{k}") for k in K}
    theta_k = {k: solver.BoolVar(f"theta_k_{k}") for k in K}
    tau = {k: solver.NumVar(0, inf, f"tau_{k}") for k in K}
    w = {k: solver.NumVar(0, inf, f"w_{k}") for k in K}
    z = {i: solver.NumVar(0, inf, f"z_{i}") for i in P}
    utilde = {i: solver.NumVar(0, inf, f"utilde_{i}") for i in V}
    sigma = {(k, i, j): solver.NumVar(-inf, inf, f"sigma_{k}_{i}_{j}") for k in K for (i, j) in A}
    if ev:
        soc_a = {k: solver.NumVar(0, inf, f"soc_a_{k}") for k in K}
        soc_b = {k: solver.NumVar(0, inf, f"soc_b_{k}") for k in K}
        cdt = {k: solver.NumVar(0, inf, f"cdt_{k}") for k in K}

    objective = solver.Objective()
    for k in K:
        for (i, j) in A:
            objective.SetCoefficient(x[k, i, j], c[i, j])
    objective.SetMinimization()

    def eq(lhs_expr, rhs_value):
        solver.Add(lhs_expr == rhs_value)

    for i in P + D:
        eq(sum(x[k, i, j] for k in K for j in V if (i, j) in c), 1)

    for k in K:
        solver.Add(sum(data["q"][i] * x[k, i, j] for i in P for j in V if (i, j) in c) <= data["Q"])
        solver.Add(sum(data["q"][i] * x[k, i, j] for i in D for j in V if (i, j) in c) <= data["Q"])
        eq(sum(x[k, "o1", j] for j in P), 1)
        eq(sum(x[k, "o3", j] for j in D), 1)
        eq(sum(x[k, j, "o2"] for j in P), 1)
        eq(sum(x[k, j, "o4"] for j in D), 1)
        for h in P + D:
            inflow = sum(x[k, i, h] for i in V if (i, h) in c)
            outflow = sum(x[k, h, j] for j in V if (h, j) in c)
            eq(inflow - outflow, 0)
        for (i, j) in A:
            solver.Add(u[k, j] >= u[k, i] + c[i, j] - M * (1 - x[k, i, j]))
        for i in P + D:
            e_i, l_i = data["tw"][i]
            solver.Add(u[k, i] >= e_i)
            solver.Add(u[k, i] <= l_i)
        solver.Add(u[k, "o1"] >= data["e_o1"])
        solver.Add(u[k, "o4"] <= data["l_o4"])
        for i in P:
            rhs = (sum(x[k, i, j] for j in (P + ["o2"]) if j != i and (i, j) in c)
                   - sum(x[k, i + n, j] for j in (D + ["o4"]) if j != i + n and (i + n, j) in c))
            eq(eta[k, i] - theta[k, i] - rhs, 0)
            solver.Add(eta[k, i] + theta[k, i] <= 1)
        s_eta = sum(eta[k, i] for i in P)
        s_theta = sum(theta[k, i] for i in P)
        solver.Add((1 / M) * s_eta <= eta_k[k])
        solver.Add(eta_k[k] <= s_eta)
        solver.Add((1 / M) * s_theta <= theta_k[k])
        solver.Add(theta_k[k] <= s_theta)
        eq(tau[k] - u[k, "o2"] - data["a"] * eta_k[k] - data["beta"] * sum(data["q"][i] * eta[k, i] for i in P), 0)
        solver.Add(w[k] >= tau[k])
        eq(u[k, "o3"] - w[k] - data["a"] * theta_k[k] - data["beta"] * sum(data["q"][i] * theta[k, i] for i in P), 0)
        for i in P:
            solver.Add(w[k] >= z[i] - M * (1 - theta[k, i]))
            solver.Add(z[i] >= tau[k] - M * (1 - eta[k, i]))
        solver.Add(u[k, "o2"] - u[k, "o1"] <= data["T"])
        solver.Add(u[k, "o4"] - u[k, "o3"] <= data["T"])
        for (i, j) in A:
            if j in (P + D):
                eq(utilde[j] + sigma[k, i, j] - u[k, j], 0)
                solver.Add(sigma[k, i, j] <= M * (1 - x[k, i, j]))
                solver.Add(sigma[k, i, j] >= -M * (1 - x[k, i, j]))
        if ev:
            # énergie sur TOUS les arcs de la phase (y compris o1->1er arrêt, o3->1er arrêt)
            pickup_energy = sum(c[i, j] * x[k, i, j] * e_rate for i in ["o1"] + P for j in V if (i, j) in c)
            delivery_energy = sum(c[i, j] * x[k, i, j] * e_rate for i in ["o3"] + D for j in V if (i, j) in c)
            solver.Add(pickup_energy <= soc_max - soc_min)
            eq(soc_a[k] - soc_max + pickup_energy, 0)
            eq(cdt[k] - data["a"] * eta_k[k] - data["beta"] * sum(data["q"][i] * eta[k, i] for i in P)
               - data["a"] * theta_k[k] - data["beta"] * sum(data["q"][i] * theta[k, i] for i in P), 0)
            # v en kW, CDt en secondes -> kWh = v * CDt / 3600
            eq(soc_b[k] - v_charge * cdt[k] / 3600.0 - soc_a[k], 0)
            solver.Add(soc_b[k] <= soc_max)
            solver.Add(delivery_energy <= soc_b[k] - soc_min)

    for i in P:
        eq(r[i] - utilde[i + n] + utilde[i], 0)
        solver.Add(r[i] <= data["L"])

    if valid_ineq:
        # Désigualités valides de l'article (25)-(27) + élimination de sous-tours.
        # Elles ne changent pas la solution optimale ; elles resserrent la relaxation.
        e_of = {i: data["tw"][i][0] for i in P + D}
        l_of = {i: data["tw"][i][1] for i in P + D}
        e_of["o1"], l_of["o4"] = data["e_o1"], data["l_o4"]
        for k in K:
            for i in P + D:
                # (25) u_i >= e_i + sum_j max(0, e_j - e_i + t_ji) x_ji   (j a une fenêtre connue)
                solver.Add(u[k, i] >= e_of[i] + sum(max(0.0, e_of[j] - e_of[i] + c[j, i]) * x[k, j, i]
                                                    for j in V if (j, i) in c and j in e_of))
                # (26) forme valide : u_i <= l_i - sum_j max(0, l_i - l_j + t_ij) x_ij
                # (l'article l'imprime avec un « + », qui ne resserre rien)
                solver.Add(u[k, i] <= l_of[i] - sum(max(0.0, l_of[i] - l_of[j] + c[i, j]) * x[k, i, j]
                                                    for j in V if (i, j) in c and j in l_of))
        for group in (P, D):
            for a_i in range(len(group)):
                for b_i in range(a_i + 1, len(group)):
                    i, j = group[a_i], group[b_i]
                    solver.Add(sum(x[k, i, j] + x[k, j, i] for k in K) <= 1)   # pas de sous-tour à 2 sommets
        for i in P:
            # (27) borne inférieure de ride time (forme sûre, sans le terme de manutention)
            solver.Add(r[i] >= c[i, "o2"] + c["o3", i + n] if ("o3", i + n) in c else r[i] >= 0)

    status = solver.Solve()
    return solver, status, x


def find_min_fleet_scip(data, ev, k_start=2, k_max=6, time_limit_s=120):
    for k in range(k_start, k_max + 1):
        solver, status, x = build_and_solve_scip(data, k, ev=ev, time_limit_s=time_limit_s)
        if status == pywraplp.Solver.OPTIMAL:
            return k, solver.Objective().Value(), solver.NumConstraints(), solver.wall_time() / 1000, "OPTIMAL"
        elif status == pywraplp.Solver.FEASIBLE:
            return k, solver.Objective().Value(), solver.NumConstraints(), solver.wall_time() / 1000, "FEASIBLE(nao provado otimo)"
    return None, None, None, None, "INFEASIBLE_UP_TO_KMAX"
