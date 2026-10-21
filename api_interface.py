"""
Couche d'accès pour l'interface graphique (projet CL02, PDPCDEVs).

L'interface n'a besoin d'importer QUE ce module. Il ne dépend pas de Gurobi
(uniquement OR-Tools/SCIP), donc l'exécutable n'a besoin d'aucune licence.

Fonctions principales
---------------------
instance_exemple_article()            réseau à 4 demandes de l'article (Fig. 2)
generer_instance(n, graine)           instance synthétique (avec coordonnées)
charger_instance(chemin) / sauvegarder_instance(data, chemin)    fichiers JSON
trouver_k_minimal(data, ev, ...)      plus petite flotte pour laquelle l'ALNS sait construire une solution
resoudre(data, methode, K, ev, ...)   ALNS ou exact, CV ou VE ; renvoie un dictionnaire de résultats
comparer(data, K, ev, ...)            lance les deux méthodes et calcule l'écart
detail_solution(data, solution, ev)   horaires, énergie, distances, transferts, par véhicule
exporter_json(resultat, chemin) / exporter_csv(resultat, chemin)

Conventions
-----------
  * n demandes : demande i = (collecte au sommet i, livraison au sommet n+i), i = 1..n
  * solution = {"pickup": {k: [i, ...]}, "delivery": {k: [i, ...]}}
    - listes ordonnées d'identifiants de DEMANDES (1..n), jamais de n+i
    - tous les véhicules 1..K ont une liste de collecte ET de livraison non vides
    - la demande i peut être collectée par k1 et livrée par k2 != k1 : c'est un transfert au crossdock
  * temps en secondes, énergie en kWh, puissance de recharge en kW
"""
import json
import math
import time

from ortools.linear_solver import pywraplp

import instance_n4 as _n4
from alns_solver import alns, construct_initial
from instance_generator import generate_instance, arc_cost_generic
from route_eval_alns import evaluate_full
from scip_solver import build_and_solve_scip

PARAMS_VE_DEFAUT = {"e_rate": 0.2, "soc_max": 120.0, "v_charge": 150.0}   # kWh/km, kWh, kW
METHODES = ("alns", "exact")


def _acf(data, i, j):
    return arc_cost_generic(data, i, j)


def _params_ve(ev, params_ve):
    if not ev:
        return {}
    p = dict(PARAMS_VE_DEFAUT)
    p.update(params_ve or {})
    return p


# ------------------------------------------------------------------ instances
def instance_exemple_article():
    """Réseau à 4 demandes (Fig. 2 de l'article de 2023). Pas de coordonnées : seulement des distances."""
    return {
        "n": _n4.n, "P": list(_n4.P), "D": list(_n4.D), "t": dict(_n4.t), "t_cd": dict(_n4.t_cd),
        "q": dict(_n4.q), "tw": dict(_n4.tw), "Q": 20, "T": 480, "L": _n4.L, "a": _n4.a,
        "beta": _n4.beta, "e_o1": _n4.e_o1, "l_o4": _n4.l_o4, "M": _n4.M, "coords": None,
        "nom": "Réseau de l'article (4 demandes)", "K_suggere": 2,
    }


def generer_instance(n, graine=42):
    """Instance synthétique de n demandes ; data['coords'] contient les coordonnées (clé 'CD' pour le crossdock)."""
    data = generate_instance(n, seed=graine)
    data["nom"] = f"Instance synthétique n={n}, graine {graine}"
    return data


def instance_depuis_coordonnees(points, crossdock=(0.0, 0.0), Q=20, T=480, L=550, a=10, beta=1,
                                e_o1=0, l_o4=10**6, nom="Instance personnalisée"):
    """
    points : liste de dicts {"id": 1..2n, "x":..., "y":..., "q":..., "e":..., "l":...}
             ids 1..n = collectes, ids n+1..2n = livraisons ; q d'une livraison = q de sa collecte.
    Distances euclidiennes ; coût = temps de trajet.
    """
    pts = {int(p["id"]): p for p in points}
    n = len(pts) // 2
    if sorted(pts) != list(range(1, 2 * n + 1)):
        raise ValueError("les identifiants doivent être exactement 1..2n")
    coords = {i: (float(pts[i]["x"]), float(pts[i]["y"])) for i in pts}
    coords["CD"] = (float(crossdock[0]), float(crossdock[1]))
    P, D = list(range(1, n + 1)), list(range(n + 1, 2 * n + 1))
    dist = lambda u, v: math.hypot(coords[u][0] - coords[v][0], coords[u][1] - coords[v][1])
    t = {(i, j): dist(i, j) for g in (P, D) for i in g for j in g if i != j}
    t_cd = {i: dist("CD", i) for i in P + D}
    q = {i: float(pts[i]["q"]) for i in P}
    q.update({i + n: q[i] for i in P})
    tw = {i: (float(pts[i]["e"]), float(pts[i]["l"])) for i in P + D}
    return {"n": n, "P": P, "D": D, "t": t, "t_cd": t_cd, "q": q, "tw": tw, "Q": Q, "T": T, "L": L, "a": a,
            "beta": beta, "e_o1": e_o1, "l_o4": l_o4, "M": 10_000, "coords": coords, "nom": nom}


def sauvegarder_instance(data, chemin):
    """JSON. Avec coordonnées : format « points » ; sans : format « distances »."""
    n = data["n"]
    base = {k: data[k] for k in ("Q", "T", "L", "a", "beta", "e_o1", "l_o4")}
    base["nom"] = data.get("nom", "")
    if data.get("coords"):
        c = data["coords"]
        base["format"] = "points"
        base["crossdock"] = list(c["CD"])
        base["points"] = [{"id": i, "x": c[i][0], "y": c[i][1], "q": data["q"][i],
                           "e": data["tw"][i][0], "l": data["tw"][i][1]} for i in range(1, 2 * n + 1)]
    else:
        base["format"] = "distances"
        base["n"] = n
        base["t"] = {f"{i},{j}": v for (i, j), v in data["t"].items()}
        base["t_cd"] = {str(i): v for i, v in data["t_cd"].items()}
        base["q"] = {str(i): v for i, v in data["q"].items()}
        base["tw"] = {str(i): list(v) for i, v in data["tw"].items()}
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(base, f, indent=1, ensure_ascii=False)


def charger_instance(chemin):
    with open(chemin, encoding="utf-8") as f:
        d = json.load(f)
    gen = {k: d[k] for k in ("Q", "T", "L", "a", "beta", "e_o1", "l_o4") if k in d}
    if d.get("format") == "points":
        return instance_depuis_coordonnees(d["points"], tuple(d["crossdock"]), nom=d.get("nom", chemin), **gen)
    n = d["n"]
    return {"n": n, "P": list(range(1, n + 1)), "D": list(range(n + 1, 2 * n + 1)),
            "t": {tuple(int(x) for x in k.split(",")): v for k, v in d["t"].items()},
            "t_cd": {int(k): v for k, v in d["t_cd"].items()},
            "q": {int(k): v for k, v in d["q"].items()},
            "tw": {int(k): tuple(v) for k, v in d["tw"].items()},
            "M": 10_000, "coords": None, "nom": d.get("nom", chemin), **gen}


# ------------------------------------------------------------------ flotte
def trouver_k_minimal(data, ev=False, params_ve=None, k_depart=None, k_max=None):
    """
    Plus petit K pour lequel la construction initiale de l'ALNS trouve une solution faisable,
    en partant de la borne de capacité ceil(somme des demandes / Q). Pas d'optimisation, mais
    l'échec de la construction pour les petites flottes peut être lent (n = 20 : de l'ordre de la minute).
    N'est pas forcément le K minimal du problème.
    """
    n = data["n"]
    pv = _params_ve(ev, params_ve)
    # borne inférieure valide : la charge collectée par un véhicule ne dépasse pas Q
    borne_capacite = max(1, math.ceil(sum(data["q"][i] for i in data["P"]) / data["Q"]))
    for k in range(k_depart or borne_capacite, (k_max or n) + 1):
        if construct_initial(data, k, _acf, seed=1, ev=ev, **pv) is not None:
            return k
    return None


# ------------------------------------------------------------------ résolution
def _extraire_solution_exacte(x, n, K):
    nxt = {(k, i): j for (k, i, j), v in x.items() if v.solution_value() > 0.5}
    pickup, delivery = {}, {}
    for k in range(1, K + 1):
        seq, cur = [], nxt[(k, "o1")]
        while cur != "o2":
            seq.append(cur)
            cur = nxt[(k, cur)]
        pickup[k] = seq
        seq, cur = [], nxt[(k, "o3")]
        while cur != "o4":
            seq.append(cur - n)
            cur = nxt[(k, cur)]
        delivery[k] = seq
    return {"pickup": pickup, "delivery": delivery}


def resoudre(data, methode="alns", K=None, ev=False, params_ve=None, iterations=300, graine=1,
             limite_temps_s=60, inegalites_valides=False, progress=None):
    """
    Résout une instance.

    methode        "alns" ou "exact" (SCIP, MILP)
    K              nombre de véhicules ; None -> trouver_k_minimal
    ev             False : véhicules conventionnels ; True : véhicules électriques
    params_ve      {"e_rate": kWh/km, "soc_max": kWh, "v_charge": kW} (valeurs par défaut sinon)
    iterations     ALNS : nombre d'itérations
    graine         ALNS : graine aléatoire
    limite_temps_s exact : limite de temps du solveur
    progress       ALNS : fonction progress(it, total, meilleur_cout) -> bool ; renvoyer True pour annuler

    Renvoie un dict :
      statut   "optimal" | "faisable" (exact : non prouvé optimal ; ALNS : toujours « faisable ») |
               "infaisable" (aucune solution trouvée) | "annule"
      cout, K, temps_s, solution, details (voir detail_solution), transferts, methode, ev, message
    """
    if methode not in METHODES:
        raise ValueError(f"methode doit être dans {METHODES}")
    pv = _params_ve(ev, params_ve)
    t0 = time.time()
    k_auto = False
    if K is None:
        K = trouver_k_minimal(data, ev, params_ve)
        k_auto = True
        if K is None:
            return _resultat_vide(methode, ev, None, time.time() - t0, "Aucune flotte trouvée pour construire une solution.")
    res = {"methode": methode, "ev": ev, "K": K, "k_auto": k_auto, "solution": None, "cout": None,
           "statut": "infaisable", "message": ""}

    if methode == "alns":
        sol, cout, st = alns(data, K, _acf, max_iter=iterations, seed=graine, ev=ev, progress=progress, **pv)
        res["temps_s"] = time.time() - t0
        if sol is None:
            res["message"] = "Aucune solution faisable construite avec K = %d véhicules." % K
            return res
        res.update({"solution": sol, "cout": cout, "statut": "faisable"})
    else:
        solver, st, x = build_and_solve_scip(data, K, ev=ev, time_limit_s=limite_temps_s,
                                             valid_ineq=inegalites_valides, **pv)
        res["temps_s"] = time.time() - t0
        if st == pywraplp.Solver.OPTIMAL:
            res["statut"] = "optimal"
        elif st == pywraplp.Solver.FEASIBLE:
            res["statut"] = "faisable"
            res["message"] = "Limite de temps atteinte : solution non prouvée optimale."
        else:
            res["message"] = "Aucune solution trouvée (infaisable, ou limite de temps de %d s atteinte)." % limite_temps_s
            return res
        res["solution"] = _extraire_solution_exacte(x, data["n"], K)
        res["cout"] = solver.Objective().Value()

    det = detail_solution(data, res["solution"], ev, params_ve)
    res["details"], res["transferts"] = det["vehicules"], det["transferts"]
    return res


def _resultat_vide(methode, ev, K, temps, message):
    return {"methode": methode, "ev": ev, "K": K, "solution": None, "cout": None, "statut": "infaisable",
            "temps_s": temps, "message": message, "details": [], "transferts": []}


def comparer(data, K=None, ev=False, params_ve=None, iterations=300, graine=1, limite_temps_s=60, progress=None):
    """Lance l'ALNS puis l'exact au même K. 'ecart_pct' = (ALNS - exact) / exact (None si pas de référence)."""
    if K is None:
        K = trouver_k_minimal(data, ev, params_ve)
    a = resoudre(data, "alns", K, ev, params_ve, iterations, graine, progress=progress)
    e = resoudre(data, "exact", K, ev, params_ve, limite_temps_s=limite_temps_s)
    ecart = None
    if a["cout"] is not None and e["cout"] is not None:
        ecart = (a["cout"] - e["cout"]) / e["cout"] * 100
    return {"K": K, "alns": a, "exact": e, "ecart_pct": ecart}


# ------------------------------------------------------------------ détails
def evaluer(data, solution, ev=False, params_ve=None):
    """Vérifie une solution : (faisable, cout, info). 'info' contient 'reason' si infaisable."""
    return evaluate_full(data, solution, _acf, ev=ev, **_params_ve(ev, params_ve))


def detail_solution(data, solution, ev=False, params_ve=None):
    """
    Tableau par véhicule, prêt à afficher :
      {"vehicules": [ {k, collecte:[{requete, sommet, debut_service}], livraison:[...],
                       u_o1, u_o2, u_o3, u_o4, distance_collecte, distance_livraison,
                       soc_a, soc_b, cdt, energie_collecte, energie_livraison (None si ev=False)} ],
       "transferts": [ {requete, collecte_par, livree_par} ] }
    """
    n = data["n"]
    pv = _params_ve(ev, params_ve)
    ok, cout, info = evaluate_full(data, solution, _acf, ev=ev, **pv)
    if not ok:
        raise ValueError("solution infaisable : %s" % info.get("reason"))
    pk_of = {r: k for k, seq in solution["pickup"].items() for r in seq}
    dl_of = {r: k for k, seq in solution["delivery"].items() for r in seq}

    def longueur(noeuds):
        return sum(_acf(data, noeuds[i], noeuds[i + 1]) for i in range(len(noeuds) - 1))

    vehicules = []
    for k in sorted(solution["pickup"]):
        pk, dl = solution["pickup"][k], solution["delivery"][k]
        vehicules.append({
            "k": k,
            "collecte": [{"requete": r, "sommet": r, "debut_service": info["u_pickup"][r]} for r in pk],
            "livraison": [{"requete": r, "sommet": r + n, "debut_service": info["u_delivery"][r]} for r in dl],
            "u_o1": data["e_o1"], "u_o2": info["u_o2"][k], "u_o3": info["u_o3"][k], "u_o4": info["u_o4"][k],
            "distance_collecte": longueur(["o1"] + pk + ["o2"]),
            "distance_livraison": longueur(["o3"] + [r + n for r in dl] + ["o4"]),
            "soc_a": info["soc_a"].get(k) if ev else None, "soc_b": info["soc_b"].get(k) if ev else None,
            "cdt": info["cdt"].get(k) if ev else None,
            "energie_collecte": info["energie_collecte"][k] if ev else None,
            "energie_livraison": info["energie_livraison"][k] if ev else None,
        })
    transferts = [{"requete": r, "collecte_par": pk_of[r], "livree_par": dl_of[r]}
                  for r in sorted(pk_of) if pk_of[r] != dl_of[r]]
    return {"vehicules": vehicules, "transferts": transferts, "cout": cout}


def chemins(data, solution):
    """Listes de sommets par véhicule, pour tracer une carte : [(k, 'collecte'|'livraison', [labels])]."""
    n = data["n"]
    out = []
    for k in sorted(solution["pickup"]):
        out.append((k, "collecte", ["CD"] + list(solution["pickup"][k]) + ["CD"]))
        out.append((k, "livraison", ["CD"] + [r + n for r in solution["delivery"][k]] + ["CD"]))
    return out


# ------------------------------------------------------------------ export
def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    return o


def exporter_json(resultat, chemin):
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(_jsonable(resultat), f, indent=1, ensure_ascii=False)


def exporter_csv(resultat, chemin):
    """Une ligne par arrêt : véhicule, phase, ordre, demande, sommet, début de service."""
    import csv
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["vehicule", "phase", "ordre", "demande", "sommet", "debut_service_s"])
        for v in resultat["details"]:
            for phase in ("collecte", "livraison"):
                for i, s in enumerate(v[phase], 1):
                    w.writerow([v["k"], phase, i, s["requete"], s["sommet"], round(s["debut_service"], 2)])
