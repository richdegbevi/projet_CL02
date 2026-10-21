"""
Méthode approchée : Variable Neighborhood Search (VNS) pour le PDPCD(EVs),
sous l'hypothèse de simplification documentée dans route_eval.py (pas de
transfert de charge entre véhicules).

Structures de voisinage utilisées (par ordre croissant de "puissance") :
  N1 - Relocate : déplacer une requête d'un véhicule/position vers un autre
  N2 - Swap     : échanger deux requêtes entre deux véhicules/positions
  N3 - 2-opt    : inverser un segment de la séquence d'un même véhicule

Schéma classique de VNS (Mladenović & Hansen, 1997) :
  répéter jusqu'à critère d'arrêt :
    k <- 1
    tant que k <= k_max :
      x' <- secousse (shaking) dans N_k(x)
      x'' <- recherche locale (meilleure amélioration) autour de x'
      si x'' meilleure que x : x <- x'' ; k <- 1
      sinon : k <- k+1

Extension VE : le paramètre ev=True active les contraintes de State-of-Charge
dans route_eval.evaluate_solution (équations (28)-(32)). Rappel de la
limitation documentée : sous l'hypothèse "pas de transfert entre véhicules",
CDt=0 systématiquement, donc AUCUNE recharge opportuniste n'est disponible
dans cette méthode -- contrairement au modèle exact qui l'autorise. Le VNS
peut donc être plus pessimiste (exiger plus de véhicules) que l'exact pour
le cas VE, en particulier sur des instances plus grandes.
"""
import random
import copy
from route_eval import evaluate_solution


def _eval(data, routes, arc_cost_fn, ev, e_rate, soc_max, v_charge):
    return evaluate_solution(data, routes, arc_cost_fn, ev=ev,
                              e_rate=e_rate, soc_max=soc_max, v_charge=v_charge)


def construct_initial(data, n_vehicles, arc_cost_fn, seed=1,
                       ev=False, e_rate=0.2, soc_max=120.0, v_charge=150.0):
    """Construction gloutonne : insertion la moins coûteuse, un véhicule à la fois."""
    rng = random.Random(seed)
    requests = list(data["P"])
    rng.shuffle(requests)
    routes = {k: [] for k in range(1, n_vehicles + 1)}

    for req in requests:
        best_k, best_pos, best_cost = None, None, float("inf")
        for k in routes:
            seq = routes[k]
            for pos in range(len(seq) + 1):
                trial = seq[:pos] + [req] + seq[pos:]
                trial_routes = {**routes, k: trial}
                feas, cost, _ = _eval(data, trial_routes, arc_cost_fn, ev, e_rate, soc_max, v_charge)
                if feas and cost < best_cost:
                    best_k, best_pos, best_cost = k, pos, cost
        if best_k is None:
            return None   # aucune insertion faisable trouvée (flotte trop petite)
        routes[best_k].insert(best_pos, req)

    return routes


def all_requests(routes):
    return [(k, idx, req) for k, seq in routes.items() for idx, req in enumerate(seq)]


def neighborhood_relocate(data, routes, arc_cost_fn, ev, e_rate, soc_max, v_charge,
                           best_improvement=True):
    """N1 : essaie de déplacer chaque requête vers une autre position/véhicule."""
    feas0, cost0, _ = _eval(data, routes, arc_cost_fn, ev, e_rate, soc_max, v_charge)
    best_routes, best_cost = routes, cost0 if feas0 else float("inf")
    for (k1, idx1, req) in all_requests(routes):
        for k2 in routes:
            seq1 = routes[k1][:idx1] + routes[k1][idx1 + 1:]
            for pos in range(len(routes[k2]) + (1 if k2 != k1 else 0)):
                if k2 == k1:
                    seq2 = seq1[:pos] + [req] + seq1[pos:]
                    trial = {**routes, k1: seq2}
                else:
                    seq2 = routes[k2][:pos] + [req] + routes[k2][pos:]
                    trial = {**routes, k1: seq1, k2: seq2}
                feas, cost, _ = _eval(data, trial, arc_cost_fn, ev, e_rate, soc_max, v_charge)
                if feas and cost < best_cost:
                    best_cost, best_routes = cost, copy.deepcopy(trial)
                    if not best_improvement:
                        return best_routes, best_cost
    return best_routes, best_cost


def neighborhood_swap(data, routes, arc_cost_fn, ev, e_rate, soc_max, v_charge):
    """N2 : échange la position de deux requêtes (même véhicule ou non)."""
    feas0, cost0, _ = _eval(data, routes, arc_cost_fn, ev, e_rate, soc_max, v_charge)
    best_routes, best_cost = routes, cost0 if feas0 else float("inf")
    reqs = all_requests(routes)
    for a in range(len(reqs)):
        for b in range(a + 1, len(reqs)):
            k1, idx1, r1 = reqs[a]
            k2, idx2, r2 = reqs[b]
            trial = copy.deepcopy(routes)
            if k1 == k2:
                trial[k1][idx1], trial[k1][idx2] = trial[k1][idx2], trial[k1][idx1]
            else:
                trial[k1][idx1], trial[k2][idx2] = r2, r1
            feas, cost, _ = _eval(data, trial, arc_cost_fn, ev, e_rate, soc_max, v_charge)
            if feas and cost < best_cost:
                best_cost, best_routes = cost, copy.deepcopy(trial)
    return best_routes, best_cost


def neighborhood_2opt(data, routes, arc_cost_fn, ev, e_rate, soc_max, v_charge):
    """N3 : inverse un segment de la séquence d'un même véhicule."""
    feas0, cost0, _ = _eval(data, routes, arc_cost_fn, ev, e_rate, soc_max, v_charge)
    best_routes, best_cost = routes, cost0 if feas0 else float("inf")
    for k, seq in routes.items():
        Lk = len(seq)
        for i in range(Lk):
            for j in range(i + 1, Lk):
                trial_seq = seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]
                trial = {**routes, k: trial_seq}
                feas, cost, _ = _eval(data, trial, arc_cost_fn, ev, e_rate, soc_max, v_charge)
                if feas and cost < best_cost:
                    best_cost, best_routes = cost, copy.deepcopy(trial)
    return best_routes, best_cost


def shake(data, routes, k_neighborhood, rng):
    """Perturbation aléatoire dans la structure de voisinage k_neighborhood."""
    trial = copy.deepcopy(routes)
    reqs = all_requests(trial)
    if len(reqs) < 2:
        return trial
    if k_neighborhood == 1:  # relocate aléatoire
        k1, idx1, req = rng.choice(reqs)
        trial[k1].pop(idx1)
        k2 = rng.choice(list(trial.keys()))
        pos = rng.randint(0, len(trial[k2]))
        trial[k2].insert(pos, req)
    elif k_neighborhood == 2:  # swap aléatoire
        a, b = rng.sample(reqs, 2)
        k1, idx1, r1 = a
        k2, idx2, r2 = b
        trial[k1][idx1], trial[k2][idx2] = r2, r1
    else:  # 2-opt aléatoire
        candidates = [kk for kk, s in trial.items() if len(s) >= 2]
        if not candidates:
            return trial
        k = rng.choice(candidates)
        seq = trial[k]
        i, j = sorted(rng.sample(range(len(seq)), 2))
        trial[k] = seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]
    return trial


NEIGHBORHOODS = {1: neighborhood_relocate, 2: neighborhood_swap, 3: neighborhood_2opt}


def vns(data, n_vehicles, arc_cost_fn, max_iter=200, seed=1, k_max=3, verbose=False,
        ev=False, e_rate=0.2, soc_max=120.0, v_charge=150.0):
    rng = random.Random(seed)
    current = construct_initial(data, n_vehicles, arc_cost_fn, seed=seed,
                                 ev=ev, e_rate=e_rate, soc_max=soc_max, v_charge=v_charge)
    if current is None:
        return None, float("inf"), "construction_infaisable"
    feas, best_cost, _ = _eval(data, current, arc_cost_fn, ev, e_rate, soc_max, v_charge)
    best_routes = copy.deepcopy(current)

    it = 0
    no_improve = 0
    while it < max_iter:
        k = 1
        while k <= k_max:
            shaken = shake(data, best_routes, k, rng)
            improved_routes, improved_cost = NEIGHBORHOODS[k](
                data, shaken, arc_cost_fn, ev, e_rate, soc_max, v_charge)
            if improved_cost < best_cost - 1e-6:
                best_routes, best_cost = improved_routes, improved_cost
                k = 1
                no_improve = 0
                if verbose:
                    print(f"  iter {it} : amélioration -> {best_cost:.2f} (voisinage N{k})")
            else:
                k += 1
        it += 1
        no_improve += 1
        if no_improve > 30:   # arrêt anticipé si stagnation prolongée
            break

    return best_routes, best_cost, "OK"
