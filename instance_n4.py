"""
Instance "jouet" (n = 4 demandes) reconstruite à partir de :
Gkiotsalitis, K. & Nikolopoulou, A. (2023) "The Pickup and Delivery Problem
with Crossdock for Perishable Goods", IEEE ITSC 2023.

Les temps de trajet tij ont été extraits visuellement de la Fig. 2
(rasterisée en haute résolution) et VALIDÉS en reconstruisant les routes
optimales du Tableau II :
  - pickup véh.1 : o1->3->1->o2 = 37.76+12.02+49.85 = 99.63  (article : 99.813)
  - pickup véh.2 : o1->2->4->o2 = 67.72+50.49+51.82 = 170.03 (article : 170.025)
  - delivery véh.1 : o3->7->5->o4 = 149.01+66.72+153.58 = 369.31 (article : 369.310)
  - delivery véh.2 : o3->6->8->o4 = 90.32+157.50+214.26 = 462.08 (article : 462.086)
Les petits écarts (<0.2 sur ~370, soit <0.06%) viennent de l'arrondi à
2 décimales indiqué dans la légende de la Fig. 2 elle-même ("arc travel
times are rounded to two decimal points") -- la coïncidence quasi parfaite
des 4 sommes confirme que la correspondance étiquette->arête est correcte.
"""

n = 4                        # nombre de demandes
P = [1, 2, 3, 4]              # sommets de collecte
D = [5, 6, 7, 8]               # sommets de livraison (n+i)
K = [1, 2]                     # véhicules

# --- temps de trajet (== coûts, cij = tij dans l'article) ------------------
# côté P (collecte) - 6 paires + 4 liaisons au crossdock (CD)
t = {}
t[(1, 2)] = t[(2, 1)] = 33.69
t[(1, 3)] = t[(3, 1)] = 12.02
t[(1, 4)] = t[(4, 1)] = 62.74
t[(2, 3)] = t[(3, 2)] = 40.13
t[(2, 4)] = t[(4, 2)] = 50.49
t[(3, 4)] = t[(4, 3)] = 57.62
t_cd = {1: 49.85, 2: 67.72, 3: 37.76, 4: 51.82}   # CD <-> sommet de collecte

# côté D (livraison) - même logique
t[(5, 6)] = t[(6, 5)] = 72.74
t[(5, 7)] = t[(7, 5)] = 66.72
t[(5, 8)] = t[(8, 5)] = 187.18
t[(6, 7)] = t[(7, 6)] = 60.82
t[(6, 8)] = t[(8, 6)] = 157.50
t[(7, 8)] = t[(8, 7)] = 120.68
t_cd.update({5: 153.58, 6: 90.32, 7: 149.01, 8: 214.26})  # CD <-> sommet de livraison

# --- demandes ----------------------------------------------------------
q = {1: 16, 2: 10, 3: 4, 4: 4}
q.update({5: 16, 6: 10, 7: 4, 8: 4})   # qi = qi-n pour i dans D

# --- fenêtres de temps (Tableau I) ----------------------------------------
tw = {
    1: (442, 562), 2: (455, 575), 3: (360, 471), 4: (475, 595),
    5: (823, 943), 6: (852, 972), 7: (793, 913), 8: (1007, 1127),
}

# --- paramètres généraux ---------------------------------------------------
Q = {1: 20, 2: 20}          # capacité de chaque véhicule
T = {1: 480, 2: 480}        # durée maximale de route
L = 550                     # temps de trajet maximal du bien (ride time)
a = 10                      # temps fixe de manutention au crossdock
beta = 1                    # temps de manutention par unité de marchandise
e_o1, l_o4 = 360, 1320      # fenêtre du dépôt (o1 / o4)
M = 10_000                  # Big-M

# les sommets o1,o2,o3,o4 représentent le MÊME lieu physique (le crossdock) ;
# la "distance" de n'importe lequel d'entre eux à un sommet i vaut toujours t_cd[i]
def arc_cost(i, j):
    """Coût/temps de trajet de l'arc (i,j), en traitant o1,o2,o3,o4 comme CD."""
    O = {"o1", "o2", "o3", "o4"}
    if i in O and j in O:
        return 0.0
    if i in O:
        return t_cd[j]
    if j in O:
        return t_cd[i]
    return t[(i, j)]
