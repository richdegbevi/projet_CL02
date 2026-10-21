"""
Tests automatiques de api_interface.py contre les cas de référence du rapport.
Lancer :  python tests_api.py        (durée : environ 1 minute)
"""
import os
import tempfile
import time

import api_interface as api

ok_total = 0


def verifier(nom, condition, detail=""):
    global ok_total
    print(("  OK   " if condition else "  ECHEC") + " " + nom + (f"  [{detail}]" if detail else ""))
    assert condition, nom
    ok_total += 1


def proche(a, b, tol=0.02):
    return a is not None and abs(a - b) <= tol


print("1. Réseau de l'article, 4 demandes, K = 2, véhicules conventionnels (valeur de référence 1101,05)")
d4 = api.instance_exemple_article()
r = api.resoudre(d4, "alns", K=2)
verifier("ALNS : coût 1101,05", proche(r["cout"], 1101.05), f"{r['cout']:.2f}")
r = api.resoudre(d4, "exact", K=2)
verifier("exact : optimal, coût 1101,05", r["statut"] == "optimal" and proche(r["cout"], 1101.05), f"{r['cout']:.2f}")
verifier("détails par véhicule fournis", len(r["details"]) == 2 and all(v["collecte"] and v["livraison"] for v in r["details"]))

print("2. Instance synthétique n = 5, graine 42")
d5 = api.generer_instance(5, 42)
verifier("K minimal trouvé = 3", api.trouver_k_minimal(d5) == 3)
c = api.comparer(d5, K=3)
verifier("ALNS = exact = 1594,08", proche(c["alns"]["cout"], 1594.08) and proche(c["exact"]["cout"], 1594.08),
         f"ALNS {c['alns']['cout']:.2f} / exact {c['exact']['cout']:.2f}")
verifier("écart ALNS/exact nul", abs(c["ecart_pct"]) < 0.01)
verifier("la solution optimale utilise un transfert", len(c["alns"]["transferts"]) >= 1, str(c["alns"]["transferts"]))

print("3. Véhicules électriques (e = 0,2 kWh/km, 120 kWh, 150 kW)")
r = api.resoudre(d5, "exact", K=3, ev=True)
verifier("n = 5, K = 3 : infaisable", r["statut"] == "infaisable")
r = api.resoudre(d5, "alns", K=4, ev=True)
verifier("n = 5, K = 4 : 1647,93", proche(r["cout"], 1647.93), f"{r['cout']:.2f}")
verifier("état de charge renseigné", all(v["soc_a"] is not None for v in r["details"]))
verifier("état de charge ≥ SoC_min (12 kWh) partout", all(v["soc_a"] >= 12 - 1e-6 for v in r["details"]))

print("4. Callback de progression et annulation")
appels = []
r = api.resoudre(api.generer_instance(8, 42), "alns", K=6, iterations=300,
                 progress=lambda it, tot, best: (appels.append(it) or it >= 20))
verifier("l'ALNS s'arrête à la demande (itération 20)", appels and max(appels) == 20 and len(appels) == 21, f"{len(appels)} appels, un par itération")

print("5. Fichiers d'instance (aller-retour JSON)")
with tempfile.TemporaryDirectory() as tmp:
    for nom, data in (("synth", d5), ("article", d4)):
        chemin = os.path.join(tmp, nom + ".json")
        api.sauvegarder_instance(data, chemin)
        re = api.charger_instance(chemin)
        k = 3 if nom == "synth" else 2
        cout = api.resoudre(re, "alns", K=k)["cout"]
        verifier(f"instance « {nom} » rechargée : même coût", proche(cout, 1594.08 if nom == "synth" else 1101.05), f"{cout:.2f}")
    res = api.resoudre(d5, "alns", K=3)
    api.exporter_json(res, os.path.join(tmp, "res.json"))
    api.exporter_csv(res, os.path.join(tmp, "res.csv"))
    verifier("export JSON et CSV créés", os.path.getsize(os.path.join(tmp, "res.json")) > 0 and os.path.getsize(os.path.join(tmp, "res.csv")) > 0)

print("6. Vérificateur de solution")
ok, cout, info = api.evaluer(d5, {"pickup": {1: [1, 2, 3, 4, 5]}, "delivery": {1: [1, 2, 3, 4, 5]}})
verifier("une seule tournée pour 5 demandes est refusée", (not ok) and "reason" in info, info.get("reason", ""))

print("\nTous les tests passent (%d vérifications)." % ok_total)
