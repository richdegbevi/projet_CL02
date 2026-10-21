"""
Adaptive Large Neighborhood Search (ALNS) pour le PDPCD(EVs), avec
transferts de charge autorisés entre véhicules au crossdock.

Limitation documentée (voir route_eval_alns.py) : la politique de
planification temporelle est gloutonne (arrivée au plus tôt, attente
minimale) -- contrairement au modèle exact qui laisse les instants de
service totalement libres. Cela peut rendre notre évaluateur légèrement
conservateur (rejette parfois à tort une solution qu'un ordonnancement
plus fin rendrait faisable), sans jamais accepter de solution réellement
infaisable.

Schéma ALNS (Ropke & Pisinger, 2006) :
répéter jusqu'à critère d'arrêt :
    choisir un opérateur de destruction (roulette pondérée par succès passé)
    détruire q requêtes (les retirer de pickup ET delivery)
    choisir un opérateur de réparation (idem)
    réinsérer les requêtes retirées (collecte et livraison indépendamment)
    accepter/rejeter (ici : recuit simulé simplifié)
    mettre à jour les poids des opérateurs selon le résultat
"""
import random
import copy
import math
from route_eval_alns import evaluate_full


def _requests_in(routes_dict):
    return {req for seq in routes_dict.values() for req in seq}


def _construct_one_per_vehicle(data, n_vehicles, arc_cost_fn, ev, node_limit=30000, **ev_kwargs):
    """Cas K = n : chaque véhicule collecte exactement une requête et en livre
    exactement une (éventuellement une autre). Il faut alors trouver un
    appariement collecte/livraison faisable, ce que l'insertion gloutonne ne
    sait pas faire. Recherche en profondeur avec élagage : la requête r est
    collectée par le véhicule r ; on choisit, requête par requête, le véhicule
    qui la livre, en vérifiant la faisabilité de la solution partielle."""
    reqs = sorted(data["P"])
    if n_vehicles != len(reqs):
        return None
    vehicles = range(1, n_vehicles + 1)
    assigned, used, nodes = {}, set(), [0]

    def partial_solution():
        pk = {k: ([reqs[k - 1]] if reqs[k - 1] in assigned else []) for k in vehicles}
        dl = {k: [] for k in vehicles}
        for r, v in assigned.items():
            dl[v].append(r)
        return {"pickup": pk, "delivery": dl}

    def dfs(i):
        if i == len(reqs):
            return True
        nodes[0] += 1
        if nodes[0] > node_limit:
            return False
        r = reqs[i]
        for v in vehicles:
            if v in used:
                continue
            assigned[r] = v
            used.add(v)
            feas, _, _ = evaluate_full(data, partial_solution(), arc_cost_fn, ev=ev, **ev_kwargs)
            if feas and dfs(i + 1):
                return True
            used.discard(v)
            del assigned[r]
        return False

    return partial_solution() if dfs(0) else None


def construct_initial(data, n_vehicles, arc_cost_fn, seed=1, ev=False, n_retries=300, **ev_kwargs):
    """Construction gloutonne : insertion la moins coûteuse, collecte et
    livraison traitées indépendamment (permet déjà des transferts).
    Ordonne les requêtes par fenêtre de temps la plus étroite en premier
    (heuristique classique VRPTW) et retente avec plusieurs graines
    aléatoires si un ordre particulier mène à une impasse.

    Garde-fou (important quand n_vehicles s'approche du nombre de requêtes) :
    chaque véhicule devant obligatoirement avoir collecte ET livraison non
    vides (cf. route_eval_alns.py), une insertion gloutonne "myope" peut
    concentrer les requêtes sur peu de véhicules et en laisser d'autres
    vides, menant à un échec final évitable. Dès que le nombre de requêtes
    restantes égale le nombre de véhicules dont la collecte (resp. la
    livraison) est encore vide, on restreint le choix à CES véhicules pour
    garantir la couverture, côté collecte et côté livraison séparément."""
    for attempt in range(n_retries):
        rng = random.Random(seed * 1000 + attempt)
        requests = list(data["P"])
        requests.sort(key=lambda r: (data["tw"][r][1] - data["tw"][r][0]) + rng.uniform(0, 1e-3))
        if attempt > 0:
            rng.shuffle(requests)

        pickup = {k: [] for k in range(1, n_vehicles + 1)}
        delivery = {k: [] for k in range(1, n_vehicles + 1)}
        ok = True
        remaining = list(requests)

        for idx, req in enumerate(requests):
            # Chaque côté est traité séparément : un véhicule peut avoir sa collecte
            # remplie et sa livraison encore vide (c'est précisément un transfert).
            empty_p = [k for k in pickup if not pickup[k]]
            empty_d = [k for k in delivery if not delivery[k]]
            n_left = len(remaining) - idx
            candidate_p = empty_p if (empty_p and n_left <= len(empty_p)) else list(pickup.keys())
            candidate_d = empty_d if (empty_d and n_left <= len(empty_d)) else list(delivery.keys())

            options = []   # (coût, choix) de toutes les insertions faisables
            for k_p in candidate_p:
                for pos_p in range(len(pickup[k_p]) + 1):
                    trial_pickup = {**pickup, k_p: pickup[k_p][:pos_p] + [req] + pickup[k_p][pos_p:]}
                    for k_d in candidate_d:
                        for pos_d in range(len(delivery[k_d]) + 1):
                            trial_delivery = {**delivery, k_d: delivery[k_d][:pos_d] + [req] + delivery[k_d][pos_d:]}
                            sol = {"pickup": trial_pickup, "delivery": trial_delivery}
                            feas, cost, _ = evaluate_full(data, sol, arc_cost_fn, ev=ev, **ev_kwargs)
                            if feas:
                                options.append((cost, (k_p, pos_p, k_d, pos_d)))
            if not options:
                ok = False
                break
            options.sort(key=lambda o: o[0])
            # tentative 0 : choix glouton pur ; ensuite : choix aléatoire parmi les
            # meilleures options (GRASP), de plus en plus large -> diversité des
            # constructions quand le glouton pur mène à une impasse (cas VE surtout)
            width = 1 if attempt == 0 else min(len(options), 2 + attempt // 40)
            k_p, pos_p, k_d, pos_d = rng.choice(options[:width])[1]
            pickup[k_p].insert(pos_p, req)
            delivery[k_d].insert(pos_d, req)

        if ok:
            return {"pickup": pickup, "delivery": delivery}

    # repli : si K = n, recherche d'un appariement collecte/livraison faisable
    return _construct_one_per_vehicle(data, n_vehicles, arc_cost_fn, ev, **ev_kwargs)


# --- opérateurs de destruction ---------------------------------------------

def destroy_random(solution, q, rng):
    """Retire q requêtes au hasard (de leurs deux positions, collecte+livraison)."""
    all_reqs = list(_requests_in(solution["pickup"]))
    removed = set(rng.sample(all_reqs, min(q, len(all_reqs))))
    return _remove_requests(solution, removed), removed


def destroy_worst(solution, q, data, arc_cost_fn, rng):
    """Retire les q requêtes dont le retrait réduit le plus le coût (les
    plus 'chères' à desservir)."""
    all_reqs = list(_requests_in(solution["pickup"]))
    base_feas, base_cost, _ = evaluate_full(data, solution, arc_cost_fn)
    costs = []
    for req in all_reqs:
        trial = _remove_requests(solution, {req})
        feas, cost, _ = evaluate_full(data, trial, arc_cost_fn)
        delta = (base_cost - cost) if (feas and base_feas) else 0
        costs.append((delta, req))
    costs.sort(reverse=True)   # plus grand delta (plus couteux a garder) en tete
    removed = {req for _, req in costs[:q]}
    return _remove_requests(solution, removed), removed


def destroy_shaw(data, solution, q, rng):
    """Retire un groupe de requêtes géographiquement/temporellement proches
    (favorise des ré-insertions différentes mais cohérentes)."""
    all_reqs = list(_requests_in(solution["pickup"]))
    seed_req = rng.choice(all_reqs)
    e_seed, l_seed = data["tw"][seed_req]

    def relatedness(r):
        e_r, l_r = data["tw"][r]
        return abs(e_seed - e_r) + abs(l_seed - l_r)

    ordered = sorted(all_reqs, key=relatedness)
    removed = set(ordered[:q])
    return _remove_requests(solution, removed), removed


def _remove_requests(solution, removed):
    new_pickup = {k: [r for r in seq if r not in removed] for k, seq in solution["pickup"].items()}
    new_delivery = {k: [r for r in seq if r not in removed] for k, seq in solution["delivery"].items()}
    return {"pickup": new_pickup, "delivery": new_delivery}


DESTROY_OPS = ["random", "worst", "shaw"]


# --- opérateurs de réparation -----------------------------------------------

def repair_greedy(data, solution, removed, arc_cost_fn, rng, ev=False, n_retries=5, **ev_kwargs):
    """Réinsertion gloutonne : pour chaque requête retirée, la meilleure
    position (collecte ET livraison, indépendamment). Retente plusieurs
    ordres si un ordre particulier mène à une impasse."""
    for attempt in range(n_retries):
        sol = copy.deepcopy(solution)
        reqs = list(removed)
        local_rng = random.Random(rng.randint(0, 10**9) + attempt)
        local_rng.shuffle(reqs)
        ok = True
        for req in reqs:
            best_cost, best_choice = float("inf"), None
            for k_p in sol["pickup"]:
                for pos_p in range(len(sol["pickup"][k_p]) + 1):
                    trial_pickup = {**sol["pickup"],
                                     k_p: sol["pickup"][k_p][:pos_p] + [req] + sol["pickup"][k_p][pos_p:]}
                    for k_d in sol["delivery"]:
                        for pos_d in range(len(sol["delivery"][k_d]) + 1):
                            trial_delivery = {**sol["delivery"],
                                               k_d: sol["delivery"][k_d][:pos_d] + [req] + sol["delivery"][k_d][pos_d:]}
                            trial_sol = {"pickup": trial_pickup, "delivery": trial_delivery}
                            feas, cost, _ = evaluate_full(data, trial_sol, arc_cost_fn, ev=ev, **ev_kwargs)
                            if feas and cost < best_cost:
                                best_cost = cost
                                best_choice = (k_p, pos_p, k_d, pos_d)
            if best_choice is None:
                ok = False
                break
            k_p, pos_p, k_d, pos_d = best_choice
            sol["pickup"][k_p].insert(pos_p, req)
            sol["delivery"][k_d].insert(pos_d, req)
        if ok:
            return sol
    return None


REPAIR_OPS = ["greedy"]   # (extensible : regret-2, etc. -- laisse pour un travail futur)


def alns(data, n_vehicles, arc_cost_fn, max_iter=300, seed=1, verbose=False,
         ev=False, e_rate=0.2, soc_max=120.0, v_charge=150.0, progress=None):
    rng = random.Random(seed)
    ev_kwargs = dict(e_rate=e_rate, soc_max=soc_max, v_charge=v_charge) if ev else {}

    current = construct_initial(data, n_vehicles, arc_cost_fn, seed=seed, ev=ev, **ev_kwargs)
    if current is None:
        return None, float("inf"), "construction_infaisable"
    feas, current_cost, _ = evaluate_full(data, current, arc_cost_fn, ev=ev, **ev_kwargs)
    best, best_cost = copy.deepcopy(current), current_cost

    weights_destroy = {op: 1.0 for op in DESTROY_OPS}
    n_reqs = len(data["P"])
    temperature = max(best_cost * 0.05, 1.0)
    cooling = 0.995

    for it in range(max_iter):
        # callback optionnel pour une interface : progress(it, max_iter, meilleur_cout), appelé au
        # début de CHAQUE itération ; s'il renvoie True, la recherche s'arrête (annulation)
        if progress is not None and progress(it, max_iter, best_cost):
            break
        q = rng.randint(1, max(1, min(n_reqs // 3, 4)))

        op = rng.choices(DESTROY_OPS, weights=[weights_destroy[o] for o in DESTROY_OPS])[0]
        if op == "random":
            destroyed, removed = destroy_random(current, q, rng)
        elif op == "worst":
            destroyed, removed = destroy_worst(current, q, data, arc_cost_fn, rng)
        else:
            destroyed, removed = destroy_shaw(data, current, q, rng)

        repaired = repair_greedy(data, destroyed, removed, arc_cost_fn, rng, ev=ev, **ev_kwargs)

        if repaired is None:
            weights_destroy[op] *= 0.98
            continue

        feas, cost, _ = evaluate_full(data, repaired, arc_cost_fn, ev=ev, **ev_kwargs)
        if not feas:
            weights_destroy[op] *= 0.98
            continue

        accept = False
        if cost < current_cost:
            accept = True
            reward = 1.02 if cost < best_cost else 1.01
        else:
            delta = cost - current_cost
            prob = math.exp(-delta / max(temperature, 1e-6))
            if rng.random() < prob:
                accept = True
            reward = 0.995

        weights_destroy[op] *= reward

        if accept:
            current, current_cost = repaired, cost
            if cost < best_cost:
                best, best_cost = copy.deepcopy(repaired), cost
                if verbose:
                    print(f"  iter {it}: nouvelle meilleure solution -> {best_cost:.2f}")

        temperature *= cooling

    return best, best_cost, "OK"
