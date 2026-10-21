"""
Évaluateur de solution pour l'ALNS -- version complète autorisant les
TRANSFERTS de charge entre véhicules au crossdock (contrairement à
route_eval.py, utilisé par le VNS, qui l'interdisait).

Représentation d'une solution :
    solution = {
        "pickup":   {k: [id_requête, ...]},   # ordre de visite, phase collecte
        "delivery": {k: [id_requête, ...]},   # ordre de visite, phase livraison
    }
Chaque requête apparaît exactement une fois dans "pickup" (sur un véhicule)
et exactement une fois dans "delivery" (sur un véhicule, potentiellement
différent -- c'est le transfert).

Synchronisation crossdock (équations (14)-(18) et (28)-(32) de l'article) :
  - Pour chaque véhicule k, à la fin de sa route de collecte (u_o2^k), il
    décharge les requêtes qu'il transfère à un AUTRE véhicule :
    tau_k = u_o2^k + a*1{transfert sortant} + beta*sum(q_i transférées, sortant)
  - z_i = tau_{véhicule qui a collecté i}  si i est transférée, sinon
    disponible dès u_o2 de son propre véhicule
  - w_k (début de rechargement) >= tau_k (propre) et >= z_i pour toute
    requête i transférée VERS k ; comme le coût ne dépend pas du moment du
    départ, on retarde w_k jusqu'au dernier instant qui évite une attente
    inutile au premier arrêt de livraison (même logique que route_eval.py)
  - u_o3^k = w_k + a*1{transfert entrant} + beta*sum(q_i entrantes)
  - Recharge opportuniste (VE) : CDt_k = a*1{sortant}+beta*sum(sortant)
                                        + a*1{entrant}+beta*sum(entrant)
    SoC_b^k = min(SoC_a^k + v*CDt_k, SoC_max)
"""


def evaluate_full(data, solution, arc_cost_fn, ev=False,
                   e_rate=0.2, soc_max=120.0, v_charge=150.0):
    """Évalue une solution complète. Retourne (faisable, cout_total, info)."""
    n = data["n"]
    pickup, delivery = solution["pickup"], solution["delivery"]
    vehicles = set(pickup.keys()) | set(delivery.keys())
    soc_min = 0.1 * soc_max

    pickup_of, delivery_of = {}, {}
    for k, seq in pickup.items():
        for req in seq:
            pickup_of[req] = k
    for k, seq in delivery.items():
        for req in seq:
            delivery_of[req] = k

    all_reqs = set(data["P"])
    present = set(pickup_of.keys())
    if present != set(delivery_of.keys()):
        return False, float("inf"), {"reason": "incoherence_collecte_livraison"}
    if not present.issubset(all_reqs):
        return False, float("inf"), {"reason": "requête_inconnue"}
    # NB : on n'exige PAS present == all_reqs ici, pour permettre d'évaluer
    # des solutions PARTIELLES pendant la construction/réparation (ALNS).
    # La complétude est vérifiée séparément par le solveur avant de retenir
    # une solution finale.
    is_complete = (present == all_reqs)
    if is_complete:
        # Réplique fidèlement les contraintes (5)-(6) de l'article : TOUS les
        # véhicules du parc K doivent effectuer à la fois une tournée de
        # collecte ET une tournée de livraison (x_o1j^k=1 pour tout k, pas
        # seulement <=1). Un véhicule avec collecte vide mais livraison non
        # vide (ou l'inverse) n'est pas une solution valide du modèle exact.
        for k in vehicles:
            if not (pickup.get(k) and delivery.get(k)):
                return False, float("inf"), {"reason": f"vehicule_{k}_non_pleinement_utilise"}

    # --- phase 1 : routes de collecte --------------------------------------
    u_o2, tau, pickup_energy = {}, {}, {}
    u_pickup_service = {}
    total_cost = 0.0
    for k in vehicles:
        seq = pickup.get(k, [])
        if seq and sum(data["q"][i] for i in seq) > data["Q"]:
            return False, float("inf"), {"reason": f"capacite_collecte_veh_{k}"}
        prev = "o1"
        t_now = data["e_o1"]
        energy = 0.0
        cost_p = 0.0
        for req in seq:
            travel = arc_cost_fn(data, prev, req)
            t_now += travel
            cost_p += travel
            e_i, l_i = data["tw"][req]
            if t_now > l_i:
                return False, float("inf"), {"reason": f"fenetre_collecte_{req}"}
            t_now = max(t_now, e_i)
            u_pickup_service[req] = t_now
            energy += travel * e_rate     # tous les arcs de la phase (y compris o1 -> 1er arrêt)
            prev = req
        if seq:
            travel = arc_cost_fn(data, prev, "o2")
            cost_p += travel
            energy += travel * e_rate
            u_o2[k] = t_now + travel
            if u_o2[k] - data["e_o1"] > data["T"]:
                return False, float("inf"), {"reason": f"duree_collecte_veh_{k}"}
        else:
            u_o2[k] = data["e_o1"]
        total_cost += cost_p
        pickup_energy[k] = energy

        out_transf = [req for req in seq if delivery_of.get(req) != k]
        tau[k] = u_o2[k] + (data["a"] if out_transf else 0.0) \
            + data["beta"] * sum(data["q"][r] for r in out_transf)

    z = {}
    for req in present:
        pk = pickup_of[req]
        z[req] = tau[pk] if delivery_of[req] != pk else u_o2[pk]

    # --- phase 2 : routes de livraison (avec retard de depart optimal) -----
    u_delivery_service = {}
    detail = {"u_o3": {}, "u_o4": {}, "soc_a": {}, "soc_b": {}, "cdt": {}, "energie_livraison": {}}
    for k in vehicles:
        seqd = delivery.get(k, [])
        if seqd and sum(data["q"][i] for i in seqd) > data["Q"]:
            return False, float("inf"), {"reason": f"capacite_livraison_veh_{k}"}
        in_transf = [req for req in seqd if pickup_of.get(req) != k]
        w_k = tau.get(k, data["e_o1"])
        if in_transf:
            w_k = max(w_k, max(z[req] for req in in_transf))

        a_in = data["a"] if in_transf else 0.0
        beta_in = data["beta"] * sum(data["q"][r] for r in in_transf)
        if seqd:
            u_o3_probe = w_k + a_in + beta_in
            first_node = seqd[0] + n
            earliest_arrival = u_o3_probe + arc_cost_fn(data, "o3", first_node)
            e_first, _ = data["tw"][first_node]
            if earliest_arrival < e_first:
                w_k += (e_first - earliest_arrival)
        u_o3_k = w_k + a_in + beta_in
        detail["u_o3"][k] = u_o3_k

        prev = "o3"
        t_now = u_o3_k
        cost_d = 0.0
        energy_d = 0.0
        for req in seqd:
            node = req + n
            travel = arc_cost_fn(data, prev, node)
            t_now += travel
            cost_d += travel
            e_j, l_j = data["tw"][node]
            if t_now > l_j:
                return False, float("inf"), {"reason": f"fenetre_livraison_{node}"}
            t_now = max(t_now, e_j)
            u_delivery_service[req] = t_now
            energy_d += travel * e_rate   # tous les arcs de la phase (y compris o3 -> 1er arrêt)
            prev = node
        if seqd:
            travel = arc_cost_fn(data, prev, "o4")
            cost_d += travel
            energy_d += travel * e_rate
            u_o4_k = t_now + travel
            detail["u_o4"][k] = u_o4_k
            detail["energie_livraison"][k] = energy_d
            if u_o4_k - u_o3_k > data["T"]:
                return False, float("inf"), {"reason": f"duree_livraison_veh_{k}"}
            if u_o4_k > data["l_o4"]:
                return False, float("inf"), {"reason": f"horizon_depasse_veh_{k}"}
        total_cost += cost_d

        if ev:
            soc_a = soc_max - pickup_energy.get(k, 0.0)
            if soc_a < soc_min - 1e-9:
                return False, float("inf"), {"reason": f"soc_collecte_veh_{k}"}
            out_transf = [req for req in pickup.get(k, []) if delivery_of.get(req) != k]
            cdt_k = (data["a"] if out_transf else 0.0) \
                + data["beta"] * sum(data["q"][r] for r in out_transf) + a_in + beta_in
            # (30)-(31) : SoC_b = SoC_a + v * CDt, avec v en kW et CDt en secondes
            # -> conversion en heures (/3600). Sans cette conversion (erreur
            # de notre première version), la recharge valait des milliers de
            # kWh et rendait faussement infaisable tout transfert au crossdock.
            soc_b = soc_a + v_charge * cdt_k / 3600.0
            # (31) SoC_b <= SoC_max n'est vérifiée que sur une solution COMPLÈTE :
            # sur une solution partielle, un véhicule sans collecte a encore sa
            # batterie pleine, et la contrainte n'est pas monotone (elle devient
            # satisfaite quand le véhicule reçoit ensuite une collecte) ; la
            # appliquer trop tôt écarterait à tort des solutions complètes faisables.
            detail["soc_a"][k], detail["soc_b"][k], detail["cdt"][k] = soc_a, soc_b, cdt_k
            if is_complete and soc_b > soc_max + 1e-9:
                return False, float("inf"), {"reason": f"soc_surcharge_veh_{k}"}
            if energy_d > soc_b - soc_min + 1e-9:
                return False, float("inf"), {"reason": f"soc_livraison_veh_{k}"}

    for req in present:
        r_i = u_delivery_service[req] - u_pickup_service[req]
        if r_i > data["L"]:
            return False, float("inf"), {"reason": f"ride_time_{req}"}

    info = {"u_o2": u_o2, "tau": tau, "z": z,
            "u_pickup": u_pickup_service, "u_delivery": u_delivery_service,
            "energie_collecte": pickup_energy}
    info.update(detail)
    return True, total_cost, info
