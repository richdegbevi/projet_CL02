"""
Générateur d'instances synthétiques pour n = 5..10 demandes, dans le même
style que l'instance validée (instance_n4.py) : coordonnées aléatoires
autour du crossdock, distances euclidiennes comme tij/cij, demandes tirées
du même ensemble de valeurs que l'article {4, 10, 16}, fenêtres de temps
étalées sur un horizon similaire.

ATTENTION (limitation méthodologique à documenter dans le rapport) :
Contrairement à l'instance n=4 (données réelles extraites de la Fig.2 de
Gkiotsalitis & Nikolopoulou 2023), ces instances sont GÉNÉRÉES par nous,
car ni l'article principal ni l'article de 2023 ne publient les données
brutes pour n=5..20 (seulement les résultats agrégés, Tableau 7 / Tableau IV).
Elles servent à étudier le COMPORTEMENT du modèle (CV vs EV, taille de
flotte, CPU) à l'échelle, pas à reproduire un chiffre exact de l'article.
"""
import random
import math

CD_COORD = (0.0, 0.0)


def generate_instance(n_requests, seed=42):
    rng = random.Random(seed)
    P = list(range(1, n_requests + 1))
    D = list(range(n_requests + 1, 2 * n_requests + 1))

    # coordonnées : crossdock à l'origine, points dispersés dans un rayon
    # cohérent avec les échelles de distance vues dans l'instance n=4
    # (les distances au CD variaient entre ~38 et ~215)
    coords = {}
    for i in P:
        r = rng.uniform(30, 110)
        ang = rng.uniform(0, 2 * math.pi)
        coords[i] = (r * math.cos(ang), r * math.sin(ang))
    for idx, i in enumerate(D):
        r = rng.uniform(60, 215)
        ang = rng.uniform(0, 2 * math.pi)
        coords[i] = (r * math.cos(ang), r * math.sin(ang))

    def dist(a, b):
        (x1, y1), (x2, y2) = coords[a], coords[b]
        return math.hypot(x2 - x1, y2 - y1)

    t = {}
    for i in P:
        for j in P:
            if i != j:
                t[(i, j)] = dist(i, j)
    for i in D:
        for j in D:
            if i != j:
                t[(i, j)] = dist(i, j)
    t_cd = {i: math.hypot(*coords[i]) for i in P + D}

    # demandes tirées du même ensemble {4, 10, 16} que l'article
    demand_values = [4, 10, 16]
    q = {}
    for i in P:
        q[i] = rng.choice(demand_values)
    for idx, i in enumerate(P):
        q[i + n_requests] = q[i]   # qi = qi-n

    # fenêtres de temps : horizon similaire a l'instance n=4 (360 a 1320s)
    tw = {}
    for i in P:
        start = rng.uniform(360, 620)
        tw[i] = (start, start + rng.uniform(90, 150))
    for i in P:
        j = i + n_requests
        start = tw[i][1] + rng.uniform(250, 400)   # entrega depois da coleta + folga
        tw[j] = (start, start + rng.uniform(90, 150))

    return {
        "coords": {**coords, "CD": CD_COORD},
        "n": n_requests,
        "P": P,
        "D": D,
        "t": t,
        "t_cd": t_cd,
        "q": q,
        "tw": tw,
        "Q": 20,
        "T": 480,
        "L": 550,
        "a": 10,
        "beta": 1,
        "e_o1": 300,
        "l_o4": 1600,
        "M": 10_000,
    }


def arc_cost_generic(data, i, j):
    O = {"o1", "o2", "o3", "o4"}
    if i in O and j in O:
        return 0.0
    if i in O:
        return data["t_cd"][j]
    if j in O:
        return data["t_cd"][i]
    return data["t"][(i, j)]
