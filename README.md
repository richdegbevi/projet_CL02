# Projet CL02 — PDPCDEVs : code, validation et résultats

Article étudié : Nisyrios, Dimopoulos & Gkiotsalitis (2026), *Operational Research* 26:86.
Modèle de base : Gkiotsalitis & Nikolopoulou (2023), IEEE ITSC.

## Contenu

| Fichier | Rôle |
|---|---|
| `instance_n4.py` | Réseau à 4 demandes (Fig. 2 de l'article de 2023) : temps de trajet lus sur la figure et recoupés avec le Tableau II |
| `pdpcd_exact.py` | MILP du modèle de base (véhicules conventionnels), équations (1)-(24), Gurobi |
| `pdpcd_ev.py` | Extension véhicules électriques, équations (28)-(32), Gurobi |
| `instance_generator.py` | Générateur d'instances synthétiques (n quelconque, graine fixe) |
| `generic_solver.py` | MILP générique CV/VE, taille de flotte variable, Gurobi |
| `scip_solver.py` | Même MILP avec SCIP (OR-Tools), sans limite de taille de licence ; option `valid_ineq` (inégalités valides) |
| `route_eval.py`, `vns_solver.py` | Première méthode approchée (VNS, sans transfert de charge) |
| `route_eval_alns.py`, `alns_solver.py` | ALNS avec transferts de charge au crossdock |
| `run_table.py` | Expérience n = 1 à 20 (ALNS et exact au même K) |
| `run_robustesse.py`, `run_robustesse2.py` | Tests de robustesse : 5 graines de l'ALNS ; 5 instances par taille contre l'exact (n = 6, 8, 10, 12) ; 5 instances ALNS seul (n = 15, 20) |
| `api_interface.py` | Couche d'accès pour l'interface graphique : instances, résolution (ALNS ou exact, CV ou VE), détails par véhicule, export. Sans dépendance à Gurobi |
| `tests_api.py`, `demo_api.py`, `requirements.txt` | Tests automatiques de l'API (16 vérifications), démonstration en ligne de commande, dépendances |
| `exemples_instances/` | Trois instances au format JSON (réseau de l'article, synthétiques n = 8 et n = 12) |
| `diag_ev.py` | Diagnostic : une solution du MILP est-elle acceptée par l'évaluateur de l'ALNS ? |
| `resultats_n1_n20.csv` / `.json`, `robustesse_*.csv` / `.json` | Résultats de la comparaison n = 1 à 20 et des tests de robustesse |

## Corrections apportées aux contraintes du code (version VE)

Une remarque de l'enseignant (l'erreur est probablement dans les contraintes du code) nous a fait revoir les contraintes VE. Deux erreurs de **notre code** ont été trouvées en le comparant aux tableaux de l'article :

1. **Recharge sans conversion d'unités.** La puissance v est en kW et le temps des instances en secondes : l'énergie rechargée est `v × CDt / 3600` (kWh). Notre première version utilisait `v × CDt`, soit des milliers de kWh. Preuve : dans le Tableau 12, ΔSoC × 3600 / v donne les mêmes temps d'arrêt (18, 49, 66 s) pour v = 50, 100, 150, 250 et 300 kW.
2. **Énergie sans l'arc de départ.** Nous sommions l'énergie seulement sur les arcs d'origine P (resp. D), comme l'équation imprimée. Les résultats de l'article comptent la route entière : SoC_a = 99,27 et 104,90 (Tableau 12) correspondent à 2 × 51,82 et 2 × 37,76 ; le Tableau 5 donne énergie = 0,2 × coût.

Ces erreurs avaient été présentées à tort, dans des versions précédentes de nos documents, comme des faiblesses de l'article. **Ce n'en sont pas** : ce sont des erreurs de notre implémentation. Les contraintes du modèle CV n'étaient pas concernées.

Contrôle indépendant après correction : voir « Vérifications sur les tableaux de l'article » plus bas (onze valeurs du Tableau 8 reproduites à 0,1 kWh près).

## Autres corrections de l'ALNS

- Évaluation de solutions partielles (construction incrémentale).
- Contrainte (5)-(6) : tous les véhicules de K font collecte ET livraison (égalité stricte).
- Construction initiale : couverture des véhicules vides traitée séparément côté collecte et côté livraison ; tentatives aléatoires parmi les meilleures insertions (300 essais).

## Validation du modèle exact

Réseau à 4 demandes : coût 1101,050 contre 1101,234 publié (écart 0,017 %, arrondi à deux décimales de la figure), nœuds explorés identiques (NE = 1). Notre modèle compte 402 contraintes contre 1091 dans le Tableau IV de l'article de 2023 : écart **non élucidé** (peut-être une différence de comptage).

## Comparaison exact / ALNS, n = 1 à 20 (modèle CV)

Instances synthétiques (graine 42), même K pour les deux méthodes. « Exact » est la meilleure solution du solveur (SCIP) ; quand il n'a pas prouvé l'optimalité, c'est la meilleure solution trouvée dans le temps imparti (60 s pour n ≤ 9, 90 s ensuite). ALNS vs exact = (ALNS − Exact) / Exact. Temps ALNS : une exécution à K fixé.

| n | K | ALNS | Exact | Statut de l'exact | Temps exact | Temps ALNS | ALNS vs exact |
|---|---|---|---|---|---|---|---|
| 1 | 1 | 367,57 | 367,57 | optimal prouvé | 0,7 s | < 0,1 s | 0 % |
| 2 | 2 | 1011,19 | 1011,19 | optimal prouvé | < 0,1 s | < 0,1 s | 0 % |
| 3 | 2 | 995,75 | 995,75 | optimal prouvé | < 0,1 s | 0,1 s | 0 % |
| 4 | 3 | 1211,96 | 1211,96 | optimal prouvé | 0,3 s | 0,1 s | 0 % |
| 5 | 3 | 1594,08 | 1594,08 | optimal prouvé | 0,3 s | 0,1 s | 0 % |
| 6 | 4 | 1941,87 | 1941,87 | optimal prouvé | 4,3 s | 0,4 s | 0 % |
| 7 | 6 | 2680,77 | 2680,77 | optimal prouvé | 0,3 s | 0,8 s | 0 % |
| 8 | 6 | 3170,28 | 3170,28 | non prouvé | 60 s (limite) | 1,2 s | 0 % |
| 9 | 6 | 3164,95 | 2964,90 | optimal prouvé | 2,7 s | 1,3 s | +6,7 % |
| 10 | 7 | 3540,33 | 3393,29 | non prouvé | 90 s (limite) | 4,2 s | +4,3 % |
| 11 | 6 | 3243,72 | 3175,48 | non prouvé | 90 s (limite) | 2,6 s | +2,1 % |
| 12 | 8 | 3814,08 | 3792,75 | optimal prouvé | 17,8 s | 4,4 s | +0,6 % |
| 13 | 8 | 4083,31 | 4074,57 | non prouvé | 90 s (limite) | 5,2 s | +0,2 % |
| 14 | 9 | 4269,73 | — | aucune solution | 90 s (limite) | 6,6 s | — |
| 15 | 9 | 4313,53 | 4384,27 | non prouvé | 90 s (limite) | 8,0 s | −1,6 % |
| 16 | 9 | 4323,38 | — | aucune solution | 90 s (limite) | 7,7 s | — |
| 17 | 10 | 4645,07 | — | aucune solution | 90 s (limite) | 9,8 s | — |
| 18 | 12 | 5413,84 | — | aucune solution | 90 s (limite) | 13,3 s | — |
| 19 | 12 | 5665,06 | — | aucune solution | 90 s (limite) | 19,0 s | — |
| 20 | 12 | 5515,08 | — | aucune solution | 90 s (limite) | 19,5 s | — |

Les lignes n = 11 à 13, 19 et 20 de l'ALNS ont légèrement changé après la modification de la construction initiale : le résultat dépend de la solution de départ.

## Robustesse (modèle CV)

**A. Cinq graines de l'ALNS, même instance (graine 42)** (`robustesse_A.csv`)

| n | K | Min | Moyenne | Max | Écart max−min | Temps moyen |
|---|---|---|---|---|---|---|
| 10 | 7 | 3540,33 | 3540,33 | 3540,33 | 0 % | 4,3 s |
| 15 | 9 | 4313,53 | 4328,81 | 4352,32 | 0,90 % | 9,4 s |
| 20 | 12 | 5505,06 | 5534,87 | 5567,01 | 1,13 % | 18,5 s |

À n = 10 les cinq graines donnent exactement le même coût, alors que l'exact a trouvé 3393,29 : une faible variabilité ne prouve pas la qualité de la solution.

**B. Cinq instances différentes par taille (graines d'instance 1 à 5), exact limité à 45 s** (`robustesse_B.csv`, 15 instances au total) : l'ALNS égale la meilleure solution de l'exact dans 11 cas sur 15, et retrouve l'optimum prouvé dans 10 des 12 cas où l'exact l'a prouvé (écarts de +2,94 % à n = 6 et +0,29 % à n = 8). Sur les 3 cas où l'exact n'a pas prouvé son résultat : égalité, +1,01 %, et −5,62 % (ALNS meilleur). L'instance de la graine 42 semble donc défavorable à l'ALNS ; échantillon petit, à confirmer.

**C. Cinq instances à n = 12, exact limité à 90 s** (`robustesse_C.csv`)

| n | Instance | K | ALNS (graine 1) | ALNS (meilleure de 5) | Exact | Statut | Écart graine 1 | Écart meilleure de 5 |
|---|---|---|---|---|---|---|---|---|
| 12 | 1 | 8 | 3791,05 | 3791,05 | 3754,72 | non prouvé (90 s) | +0,97 % | +0,97 % |
| 12 | 2 | 9 | 4472,72 | 4443,42 | 4431,29 | optimal prouvé | +0,94 % | +0,27 % |
| 12 | 3 | 8 | 3982,39 | 3982,39 | 3982,39 | optimal prouvé | 0,00 % | −0,00 % |
| 12 | 4 | 10 | 4835,21 | 4835,21 | 4835,21 | optimal prouvé | −0,00 % | −0,00 % |
| 12 | 5 | 8 | 3702,56 | 3702,56 | 3702,56 | non prouvé (90 s) | 0,00 % | 0,00 % |

**D. Cinq instances à n = 15 et à n = 20, ALNS seul, cinq graines** (`robustesse_D.csv`) : l'exact ne trouve plus de solution à ces tailles.

| n | Instance | K | Min | Moyenne | Max | Écart max−min | Temps moyen |
|---|---|---|---|---|---|---|---|
| 15 | 1 | 9 | 4363,16 | 4474,80 | 4578,01 | 4,92 % | 7,1 s |
| 15 | 2 | 10 | 5263,85 | 5263,85 | 5263,85 | 0,00 % | 9,2 s |
| 15 | 3 | 10 | 4967,80 | 4986,47 | 4994,05 | 0,53 % | 11,2 s |
| 15 | 4 | 9 | 4749,02 | 4749,02 | 4749,02 | 0,00 % | 17,3 s |
| 15 | 5 | 9 | 4451,29 | 4482,82 | 4507,16 | 1,26 % | 7,9 s |
| 20 | 1 | 14 | 6771,62 | 6784,74 | 6808,07 | 0,54 % | 23,0 s |
| 20 | 2 | 12 | 6131,85 | 6219,05 | 6328,92 | 3,21 % | 17,6 s |
| 20 | 3 | 11 | 5635,80 | 5668,64 | 5739,01 | 1,83 % | 17,3 s |
| 20 | 4 | 11 | 5460,18 | 5487,71 | 5514,30 | 0,99 % | 15,1 s |
| 20 | 5 | 11 | 5435,25 | 5526,41 | 5604,29 | 3,11 % | 31,8 s |

**Lecture d'ensemble.** Sur les 20 instances de n = 6, 8, 10 et 12 (B et C), l'ALNS à graine 1 égale la meilleure solution de l'exact dans 14 cas ; sur les 15 où l'exact a prouvé l'optimum, il le retrouve dans 12 cas (écarts des trois autres : +2,94 % à n = 6, +0,29 % à n = 8, +0,94 % à n = 12 et +0,27 % avec la meilleure des cinq graines). Dans les cinq cas non prouvés : égalité deux fois, +1,01 % et +0,97 %, et −5,62 % (ALNS meilleur). À n = 15 et 20, l'écart entre meilleure et pire graine est en moyenne de 1,3 % et 1,9 % et atteint 4,9 % (n = 15, instance 1) : pour les grandes tailles il vaut mieux reporter la meilleure de plusieurs graines. Cet écart mesure la dispersion de l'ALNS, pas sa distance à l'optimum. La flotte trouvée varie selon l'instance (à n = 20, K de 11 à 14).


## Comparaison VE, exact / ALNS (e = 0,2 kWh/km, SoC_max = 120 kWh, v = 150 kW)

| n | K | Exact VE | ALNS VE |
|---|---|---|---|
| 5 | 3 | infaisable | infaisable |
| 5 | 4 | 1647,93 | 1647,93 |
| 6 | 4 | 1941,87 | 1941,87 |
| 6 | 5 | 2151,49 | 2151,49 |
| 7 | 6 | 2680,77 | 2680,77 |
| 7 | 7 | 2975,13 | 2975,13 |
| 8 | 6 | aucune solution en 35 s (inviabilité non prouvée) | infaisable |
| 8 | 7 | 3279,70 | 3279,70 |

L'ALNS en VE retrouve l'exact dans les huit cas (instance de graine 42). Deux corrections y ont contribué : la construction initiale traite à part collecte et livraison (avec un appariement par recherche en profondeur quand K = n) ; la contrainte (31) SoC_b ≤ SoC_max n'est vérifiée que sur une solution complète, car elle n'est pas monotone sur une solution partielle.

## Vérifications sur les tableaux de l'article

**Tableau 8 (batterie minimale, 4 demandes, 2 véhicules).** Notre modèle VE corrigé reproduit les onze valeurs à 0,1 kWh près (0,17 % au maximum), avec une capacité de véhicule non limitante :

| e (kWh/km) | Notre modèle (kWh) | Article (kWh) | Écart |
|---|---|---|---|
| 0,1 | 58,1 | 58,2 | −0,1 |
| 0,14 | 82,2 | 82,2 | +0,0 |
| 0,18 | 106,3 | 106,3 | +0,0 |
| 0,22 | 130,1 | 130,1 | +0,0 |
| 0,26 | 153,7 | 153,8 | −0,1 |
| 0,3 | 177,4 | 177,4 | +0,0 |
| 0,34 | 201,0 | 201,1 | −0,1 |
| 0,38 | 224,7 | 224,7 | +0,0 |
| 0,42 | 248,3 | 248,4 | −0,1 |
| 0,46 | 272,0 | 272,1 | −0,1 |
| 0,5 | 295,6 | 295,5 | +0,1 |

**Instance à 4 demandes de l'article de 2026 (coût 1055,0 ; Tableau 7 : 1054,98).** C'est le réseau de la Fig. 2 avec une capacité de véhicule non limitante : le coût optimal est 1101,05 pour Q ≤ 26 puis 1054,79 pour Q ≥ 30 (valeurs 27 à 29 non testées). Avec Q = 20 (article de 2023) la batterie minimale est 59,9 / 184,7 / 309,6 kWh pour e = 0,1 / 0,3 / 0,5, soit 3 à 5 % au-dessus du Tableau 8. La capacité utilisée dans l'article de 2026 n'est pas indiquée : c'est une déduction, à faire confirmer.

**Nombre de contraintes (Tableau 7 de 2026).** Notre modèle VE avec inégalités valides compte 462, 954, 1281, 1658, 2085, 2562, 4072 lignes pour (n,K) = (4,2), (5,3), (6,3), (7,3), (8,3), (9,3), (10,4), contre 561, 1168, 1561, 2014, 2527, 3100, 4967 dans l'article : rapport quasi constant (1,21 à 1,22). En comptant chaque égalité comme deux lignes (118 à 986 égalités selon le cas), on obtient 580, 1191, 1596, 2063, 2592, 3183, 5058, soit 97 à 98 % du chiffre de l'article ; le résidu (19 à 91 lignes) pourrait venir de l'élimination d'arcs, non implémentée (hypothèse non vérifiée). C'est une convention de comptage : elle ne change ni le modèle, ni la solution, ni le nombre de nœuds. Décision de l'équipe : nous rapportons notre propre décompte en précisant la convention. Les chiffres du Tableau IV de 2023 (1091 pour n = 4) sont 2 à 2,4 fois les nôtres.

**Inégalités valides (25)-(27) et sous-tours.** Implémentées comme option (`valid_ineq=True` dans `scip_solver.py`) ; elles ne changent pas l'optimum (CV n = 5, 6, 7 ; VE n = 5, 6). (26) est écrite avec un signe « − » (l'article l'imprime avec « + », ce qui ne resserre rien) ; (27) sans le terme de manutention.

## Limites connues

- Instances n ≥ 5 synthétiques (données brutes non publiées). Robustesse : 20 instances contre l'exact (n = 6, 8, 10, 12) et 10 instances ALNS seul (n = 15, 20) : résultats indicatifs.
- K issu de la recherche de l'ALNS : pas forcément minimal.
- La validation VE de l'ALNS porte sur l'instance de graine 42, n = 5 à 8.
- La planification temporelle des heuristiques est gloutonne (arrivée au plus tôt) ; le MILP laisse les instants de service libres. Biais conservateur : une solution faisable peut être rejetée, jamais l'inverse.
- Nombre de contraintes : 97 à 98 % du chiffre de 2026 en comptant chaque égalité comme deux lignes ; résidu attribué (hypothèse) à l'élimination d'arcs.
- La capacité de véhicule de l'article de 2026 n'est pas indiquée ; l'hypothèse « non limitante » reproduit le coût et le Tableau 8, mais reste une déduction.

## Interface graphique

Le cahier des charges demande un logiciel avec interface simple ; elle est construite au-dessus de `api_interface.py` (voir `specification_interface_pour_Rich.md`). Modifications apportées au code pour cela, sans changer les résultats (régression vérifiée) : l'évaluateur de l'ALNS renvoie aussi les horaires, l'énergie et le temps d'arrêt au crossdock ; `alns()` accepte un callback de progression et d'annulation ; le générateur d'instances renvoie les coordonnées ; la recherche automatique de K part de la borne de capacité. Le paquet exécutable a été testé sur Linux (PyInstaller, ALNS et solveur exact fonctionnent) ; la construction sous Windows reste à faire et à tester.
