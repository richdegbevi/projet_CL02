"""
Évaluateur de routes pour la méthode approchée (VNS).

Hypothèse de simplification (documentée dans le rapport) : chaque véhicule
livre exactement ce qu'il a lui-même collecté, dans le même ordre relatif
pour la phase de collecte et la phase de livraison. Aucun transfert de
charge entre véhicules n'est exploré par cette méthode -- ce qui, d'après
nos propres solutions exactes sur l'instance n=4, correspond au comportement
optimal observé (aucune des solutions exactes trouvées n'utilisait de
transfert). Cette hypothèse annule aussi la recharge opportuniste au
crossdock (CDt=0 quand eta_k=theta_k=0, cf. équations (14)-(18) et (30)) --
limitation à garder en tête pour le cas VE à plus grande échelle.
"""


def evaluate_solution(data, routes, arc_cost_fn, ev=False,
                       e_rate=0.2, soc_max=120.0, v_charge=150.0):
    """
    routes: dict {vehicule: [liste de requêtes dans l'ordre de visite]}
    Retourne (faisable: bool, cout_total: float, details: dict).
    """
    n = data["n"]
    total_cost = 0.0
    details = {}
    soc_min = 0.1 * soc_max

    for k, seq in routes.items():
        if not seq:
            continue

        # --- capacité ---------------------------------------------------
        total_q = sum(data["q"][i] for i in seq)
        if total_q > data["Q"]:
            return False, float("inf"), {"reason": f"capacite_depassee_veh_{k}"}

        # --- phase de collecte : o1 -> seq[0] -> seq[1] -> ... -> o2 ------
        prev = "o1"
        t_now = data["e_o1"]
        pickup_cost = 0.0
        pickup_energy = 0.0
        u_pickup = {}   # temps de début de service, par requête (phase collecte)
        for i in seq:
            travel = arc_cost_fn(data, prev, i)
            t_now = t_now + travel
            e_i, l_i = data["tw"][i]
            if t_now > l_i:
                return False, float("inf"), {"reason": f"fenetre_depassee_{i}"}
            t_now = max(t_now, e_i)   # attente si arrivée en avance
            u_pickup[i] = t_now
            pickup_cost += travel
            # CORRECTION : l'énergie est comptabilisée sur TOUS les arcs de la
            # phase, y compris o1 -> premier arrêt (cf. Tableaux 4, 5 et 12 de
            # l'article, qui comptent la route entière).
            pickup_energy += travel * e_rate
            prev = i
        travel = arc_cost_fn(data, prev, "o2")
        pickup_cost += travel
        pickup_energy += travel * e_rate
        u_o2 = t_now + travel
        if u_o2 - data["e_o1"] > data["T"]:
            return False, float("inf"), {"reason": f"duree_max_collecte_veh_{k}"}

        # --- synchronisation crossdock (sans transfert => CDt = 0) -------
        # Le départ u_o3 n'est pas simplement u_o2 : partir trop tôt et
        # attendre ensuite sur la route consomme inutilement le budget de
        # durée max T_k (l'attente APRES le départ compte dans u_o4-u_o3,
        # alors que "partir plus tard" ne coûte rien puisque le coût ne
        # dépend que des arcs parcourus). On retarde donc le départ jusqu'à
        # l'instant le plus tardif qui n'entraîne aucune attente évitable en
        # route (calcul par un passage arrière sur la séquence de livraison).
        u_o3 = u_o2
        first_stop = seq[0] + n
        earliest_arrival_first = u_o2 + arc_cost_fn(data, "o3", first_stop)
        e_first, _ = data["tw"][first_stop]
        if earliest_arrival_first < e_first:
            u_o3 = u_o2 + (e_first - earliest_arrival_first)
        if ev:
            soc_a = soc_max - pickup_energy
            if soc_a < soc_min:
                return False, float("inf"), {"reason": f"soc_insuffisant_apres_collecte_veh_{k}"}
            soc_b = soc_a   # CDt=0 => pas de recharge possible avec cette hypothese

        # --- phase de livraison : o3 -> seq[0]+n -> ... -> o4 -------------
        prev = "o3"
        t_now = u_o3
        delivery_cost = 0.0
        delivery_energy = 0.0
        u_delivery = {}
        for i in seq:
            j = i + n
            travel = arc_cost_fn(data, prev, j)
            t_now = t_now + travel
            e_j, l_j = data["tw"][j]
            if t_now > l_j:
                return False, float("inf"), {"reason": f"fenetre_depassee_{j}"}
            t_now = max(t_now, e_j)
            u_delivery[i] = t_now   # indexe par la requête i (pas par j) pour le ride time
            delivery_cost += travel
            # idem pour la livraison : l'arc o3 -> premier arrêt consomme aussi
            delivery_energy += travel * e_rate
            prev = j
        travel = arc_cost_fn(data, prev, "o4")
        delivery_cost += travel
        delivery_energy += travel * e_rate
        u_o4 = t_now + travel
        if u_o4 - u_o3 > data["T"]:
            return False, float("inf"), {"reason": f"duree_max_livraison_veh_{k}"}
        if u_o4 > data["l_o4"]:
            return False, float("inf"), {"reason": f"fin_apres_horizon_veh_{k}"}

        if ev:
            if delivery_energy > soc_b - soc_min:
                return False, float("inf"), {"reason": f"soc_insuffisant_apres_livraison_veh_{k}"}

        # --- (22) ride time : r_i = u_{n+i} - u_i <= L --------------------
        for i in seq:
            r_i = u_delivery[i] - u_pickup[i]
            if r_i > data["L"]:
                return False, float("inf"), {"reason": f"ride_time_depasse_requête_{i}"}

        total_cost += pickup_cost + delivery_cost
        details[k] = {"u_o2": u_o2, "u_o3": u_o3, "u_o4": u_o4}

    return True, total_cost, details
