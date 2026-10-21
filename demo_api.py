"""Démonstration minimale en ligne de commande de api_interface (sans interface graphique)."""
import api_interface as api

data = api.generer_instance(8, graine=42)
K = api.trouver_k_minimal(data)
print("Instance :", data["nom"], "| K minimal trouvé :", K)

res = api.resoudre(data, "alns", K=K, iterations=300)
print(f"ALNS : statut {res['statut']}, coût {res['cout']:.2f}, {res['temps_s']:.1f} s")
for v in res["details"]:
    print(f"  véhicule {v['k']} : collecte {[s['requete'] for s in v['collecte']]}  livraison {[s['requete'] for s in v['livraison']]}")
print("  transferts :", res["transferts"] or "aucun")

# Résolution exacte (SCIP via OR-Tools) sur le réseau de l'article : doit donner 1101,05 (optimal)
ex = api.resoudre(api.instance_exemple_article(), "exact", K=2)
print(f"Exact (réseau de l'article, K = 2) : statut {ex['statut']}, coût {ex['cout']:.2f}")
