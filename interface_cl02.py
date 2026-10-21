"""
Interface graphique du projet CL02 : tournées de collecte et livraison avec crossdock,
véhicules conventionnels ou électriques (PDPCD / PDPCDEVs).

Principe : cette fenêtre n'importe QUE api_interface.py ; tout le calcul est déjà fait là-bas.
Le calcul tourne dans un fil séparé (threading.Thread) pour que la fenêtre ne se fige pas ; le fil
envoie ses messages à la fenêtre par une file (queue.Queue) lue toutes les 100 ms avec after().

Lancer :   python interface_cl02.py
"""
import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
import numpy as np

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

import api_interface as api  # noqa: E402

# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------
NOM_PROGRAMME = "CL02 : tournées avec crossdock"          # nom provisoire, à décider avec Julita
N_EXACT_AVERTISSEMENT = 13       # au-delà, l'exact ne trouve en général plus de solution en 90 s
N_MAX_GENERATION = 30
COULEURS_VEHICULES = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#17becf",
                      "#e377c2", "#7f7f7f", "#bcbd22", "#393b79", "#ad494a", "#637939", "#a55194"]
COULEUR_TRANSFERT = "#d97706"
COULEURS_STATUT = {"optimal": "#1b7f5c", "faisable": "#8a5a00", "infaisable": "#b42318"}
SOC_MIN_FRACTION = 0.1           # seuil de sécurité de l'article : 10 % de la batterie (route_eval_alns.py)


def couleur(k):
    return COULEURS_VEHICULES[(k - 1) % len(COULEURS_VEHICULES)]


def fmt(x, nd=2, unite=""):
    """Nombre au format français (virgule), « — » si absent."""
    if x is None:
        return "—"
    return f"{x:,.{nd}f}".replace(",", " ").replace(".", ",") + unite


def dossier_programme():
    """Dossier du programme ; dans l'exécutable PyInstaller, c'est là que sont placés les fichiers ajoutés (--add-data)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


COPIES_CROSSDOCK = ("o1", "o2", "o3", "o4")


def _distance_schema(data, a, b):
    """Temps de trajet entre deux sommets (o1..o4 = crossdock). Pas d'arc collecte–livraison : triangle via le CD."""
    if a == b:
        return 0.0
    cd = set(COPIES_CROSSDOCK) | {"CD"}
    if a in cd and b in cd:
        return 0.0
    t_cd = data["t_cd"]
    if a in cd:
        return float(t_cd[b])
    if b in cd:
        return float(t_cd[a])
    t = data["t"]
    if (a, b) in t:
        return float(t[(a, b)])
    if (b, a) in t:
        return float(t[(b, a)])
    return float(t_cd[a]) + float(t_cd[b])


def positions_schema(data):
    """Coordonnées 2D par MDS classique à partir de data['t'] et data['t_cd'].
    Les quatre copies o1..o4 du crossdock sont regroupées en un seul point « CD ».
    Renvoie None si la matrice de distances est absente."""
    if not data.get("t") or not data.get("t_cd"):
        return None
    n = data["n"]
    sommets = list(COPIES_CROSSDOCK) + list(range(1, 2 * n + 1))
    m = len(sommets)
    D = np.zeros((m, m), dtype=float)
    for i, a in enumerate(sommets):
        for j, b in enumerate(sommets):
            D[i, j] = _distance_schema(data, a, b)
    D = 0.5 * (D + D.T)
    D2 = D ** 2
    J = np.eye(m) - np.ones((m, m)) / m
    B = -0.5 * J @ D2 @ J
    vals, vecs = np.linalg.eigh(B)
    ordre = np.argsort(vals)[::-1]
    vals, vecs = vals[ordre], vecs[:, ordre]
    xy = np.zeros((m, 2), dtype=float)
    k = 0
    for d in range(len(vals)):
        if k >= 2:
            break
        if vals[d] > 1e-12:
            xy[:, k] = vecs[:, d] * np.sqrt(vals[d])
            k += 1
    cd_xy = tuple(float(x) for x in xy[:len(COPIES_CROSSDOCK)].mean(axis=0))
    coords = {"CD": cd_xy}
    for nom in COPIES_CROSSDOCK:
        coords[nom] = cd_xy
    for i, s in enumerate(sommets[len(COPIES_CROSSDOCK):], start=len(COPIES_CROSSDOCK)):
        coords[s] = (float(xy[i, 0]), float(xy[i, 1]))
    return coords


def libelle_statut(res):
    """Texte lisible du statut d'un résultat."""
    if res["statut"] == "optimal":
        return "Optimal prouvé"
    if res["statut"] == "infaisable":
        return "Aucune solution"
    if res["methode"] == "exact":
        return "Solution faisable, optimalité non prouvée"
    return "Solution trouvée (heuristique ALNS)"


# ---------------------------------------------------------------------------
# Fenêtre principale
# ---------------------------------------------------------------------------
class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(NOM_PROGRAMME)
        self.geometry("1240x780")
        self.minsize(1050, 680)

        # état
        self.data = None                       # instance courante
        self.payload = None                    # dernier calcul (instance, paramètres, résultats)
        self.res_affiche = None                # résultat montré dans les onglets
        self.en_cours = False
        self.annuler = threading.Event()
        self.file = queue.Queue()

        self._styles()
        self._construire()
        self._charger_article()

    # ------------------------------------------------------------------ construction
    def _styles(self):
        st = ttk.Style(self)
        st.configure("Titre.TLabel", font=("TkDefaultFont", 10, "bold"))
        st.configure("Statut.TLabel", font=("TkDefaultFont", 11, "bold"), foreground="white", padding=(10, 5))
        st.configure("Lancer.TButton", font=("TkDefaultFont", 10, "bold"))
        st.configure("Treeview", rowheight=22)

    def _construire(self):
        self._barre_bas()                 # d'abord : sinon la zone principale prend tout l'espace et la barre est coupée
        haut = ttk.Frame(self)
        haut.pack(fill="both", expand=True)
        gauche = ttk.Frame(haut, padding=(10, 10, 5, 5))
        gauche.pack(side="left", fill="y")
        droite = ttk.Frame(haut, padding=(5, 10, 10, 5))
        droite.pack(side="left", fill="both", expand=True)

        self._panneau_instance(gauche)
        self._panneau_modele(gauche)
        self._panneau_methode(gauche)
        self._zone_resultats(droite)
        self._maj_etats()

    # ---- 1. instance
    def _panneau_instance(self, parent):
        cadre = ttk.LabelFrame(parent, text="1. Instance", padding=8)
        cadre.pack(fill="x", pady=(0, 8))
        self.mode_instance = tk.StringVar(value="article")
        ttk.Radiobutton(cadre, text="Réseau de l'article (4 demandes)", variable=self.mode_instance,
                        value="article", command=self._charger_article).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Radiobutton(cadre, text="Instance synthétique :", variable=self.mode_instance, value="generer",
                        command=self._maj_etats).grid(row=1, column=0, columnspan=4, sticky="w")
        ttk.Label(cadre, text="n").grid(row=2, column=0, sticky="e", padx=(18, 2))
        self.var_n = tk.StringVar(value="8")
        self.sp_n = ttk.Spinbox(cadre, from_=1, to=N_MAX_GENERATION, width=4, textvariable=self.var_n)
        self.sp_n.grid(row=2, column=1, sticky="w")
        ttk.Label(cadre, text="graine").grid(row=2, column=2, sticky="e", padx=(8, 2))
        self.var_graine_inst = tk.StringVar(value="42")
        self.en_graine_inst = ttk.Entry(cadre, width=6, textvariable=self.var_graine_inst)
        self.en_graine_inst.grid(row=2, column=3, sticky="w")
        self.bt_generer = ttk.Button(cadre, text="Générer", command=self._generer)
        self.bt_generer.grid(row=3, column=1, columnspan=3, sticky="w", pady=(3, 4))
        ttk.Radiobutton(cadre, text="Fichier JSON :", variable=self.mode_instance, value="fichier",
                        command=self._maj_etats).grid(row=4, column=0, columnspan=4, sticky="w")
        self.bt_parcourir = ttk.Button(cadre, text="Parcourir…", command=self._parcourir)
        self.bt_parcourir.grid(row=5, column=1, columnspan=3, sticky="w", pady=(3, 4))

        self.lbl_instance = ttk.Label(cadre, text="", justify="left", wraplength=290, foreground="#344054")
        self.lbl_instance.grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(cadre, text="Enregistrer l'instance…", command=self._enregistrer_instance).grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(6, 0))

    # ---- 2. modèle
    def _panneau_modele(self, parent):
        cadre = ttk.LabelFrame(parent, text="2. Modèle", padding=8)
        cadre.pack(fill="x", pady=(0, 8))
        self.var_ev = tk.BooleanVar(value=False)
        ttk.Checkbutton(cadre, text="Véhicules électriques", variable=self.var_ev,
                        command=self._maj_etats).grid(row=0, column=0, columnspan=3, sticky="w")
        defaut = api.PARAMS_VE_DEFAUT
        self.var_e = tk.StringVar(value=str(defaut["e_rate"]))
        self.var_soc = tk.StringVar(value=str(defaut["soc_max"]))
        self.var_v = tk.StringVar(value=str(defaut["v_charge"]))
        self.champs_ve = []
        for i, (txt, var, unite) in enumerate([("Consommation e", self.var_e, "kWh/km"),
                                               ("Batterie maximale", self.var_soc, "kWh"),
                                               ("Puissance de recharge v", self.var_v, "kW")], start=1):
            ttk.Label(cadre, text=txt).grid(row=i, column=0, sticky="e", padx=(18, 4), pady=1)
            e = ttk.Entry(cadre, width=7, textvariable=var)
            e.grid(row=i, column=1, sticky="w")
            ttk.Label(cadre, text=unite, foreground="#667085").grid(row=i, column=2, sticky="w", padx=4)
            self.champs_ve.append(e)

    # ---- 3. méthode
    def _panneau_methode(self, parent):
        cadre = ttk.LabelFrame(parent, text="3. Méthode", padding=8)
        cadre.pack(fill="x", pady=(0, 8))
        self.var_methode = tk.StringVar(value="alns")
        for i, (txt, val) in enumerate([("ALNS (heuristique)", "alns"), ("Solveur exact (SCIP)", "exact"),
                                        ("Comparer ALNS et exact", "comparer")]):
            ttk.Radiobutton(cadre, text=txt, variable=self.var_methode, value=val,
                            command=self._maj_etats).grid(row=i, column=0, columnspan=4, sticky="w")

        self.var_k_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(cadre, text="Flotte K automatique", variable=self.var_k_auto,
                        command=self._maj_etats).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(cadre, text="K").grid(row=3, column=2, sticky="e", pady=(8, 0))
        self.var_k = tk.StringVar(value="2")
        self.sp_k = ttk.Spinbox(cadre, from_=1, to=60, width=4, textvariable=self.var_k)
        self.sp_k.grid(row=3, column=3, sticky="w", pady=(8, 0), padx=(4, 0))

        ttk.Label(cadre, text="Itérations (ALNS)").grid(row=4, column=0, columnspan=2, sticky="e", padx=(0, 4), pady=1)
        self.var_iter = tk.StringVar(value="300")
        self.en_iter = ttk.Entry(cadre, width=7, textvariable=self.var_iter)
        self.en_iter.grid(row=4, column=2, columnspan=2, sticky="w")
        ttk.Label(cadre, text="Graine (ALNS)").grid(row=5, column=0, columnspan=2, sticky="e", padx=(0, 4), pady=1)
        self.var_graine = tk.StringVar(value="1")
        self.en_graine = ttk.Entry(cadre, width=7, textvariable=self.var_graine)
        self.en_graine.grid(row=5, column=2, columnspan=2, sticky="w")
        ttk.Label(cadre, text="Limite de temps exact (s)").grid(row=6, column=0, columnspan=2, sticky="e", padx=(0, 4), pady=1)
        self.var_limite = tk.StringVar(value="60")
        self.en_limite = ttk.Entry(cadre, width=7, textvariable=self.var_limite)
        self.en_limite.grid(row=6, column=2, columnspan=2, sticky="w")

    # ---- barre du bas : lancer / annuler / progression
    def _barre_bas(self):
        barre = ttk.Frame(self, padding=(10, 4, 10, 10))
        barre.pack(fill="x", side="bottom")
        self.bt_lancer = ttk.Button(barre, text="Lancer le calcul", style="Lancer.TButton", command=self.lancer)
        self.bt_lancer.pack(side="left")
        self.bt_annuler = ttk.Button(barre, text="Annuler", command=self.demander_annulation, state="disabled")
        self.bt_annuler.pack(side="left", padx=6)
        self.barre = ttk.Progressbar(barre, length=300, mode="determinate", maximum=100)
        self.barre.pack(side="left", padx=8)
        self.var_etat = tk.StringVar(value="Prêt.")
        ttk.Label(barre, textvariable=self.var_etat).pack(side="left", padx=8)
        self.bt_csv = ttk.Button(barre, text="Exporter CSV…", command=lambda: self._exporter("csv"), state="disabled")
        self.bt_csv.pack(side="right")
        self.bt_json = ttk.Button(barre, text="Exporter JSON…", command=lambda: self._exporter("json"), state="disabled")
        self.bt_json.pack(side="right", padx=6)

    # ---- résultats (onglets)
    def _zone_resultats(self, parent):
        entete = ttk.Frame(parent)
        entete.pack(fill="x")
        ttk.Label(entete, text="Résultats", style="Titre.TLabel").pack(side="left")
        self.var_choix = tk.StringVar()
        self.lbl_choix = ttk.Label(entete, text="Résultat affiché :")
        self.cb_choix = ttk.Combobox(entete, textvariable=self.var_choix, state="readonly", width=12, values=[])
        self.cb_choix.bind("<<ComboboxSelected>>", self._changer_affichage)

        self.onglets = ttk.Notebook(parent)
        self.onglets.pack(fill="both", expand=True, pady=(6, 0))
        self.t_resume = ttk.Frame(self.onglets, padding=12)
        self.t_tournees = ttk.Frame(self.onglets, padding=8)
        self.t_horaires = ttk.Frame(self.onglets)
        self.t_carte = ttk.Frame(self.onglets)
        self.t_energie = ttk.Frame(self.onglets, padding=8)
        self.t_compar = ttk.Frame(self.onglets, padding=12)
        for cadre, titre in [(self.t_resume, "Résumé"), (self.t_tournees, "Tournées"), (self.t_horaires, "Horaires"),
                             (self.t_carte, "Carte"), (self.t_energie, "Énergie"), (self.t_compar, "Comparaison")]:
            self.onglets.add(cadre, text=titre)

        self._init_resume()
        self._init_tournees()
        self.fig_h, self.cv_h = self._canevas(self.t_horaires)
        barre_carte = ttk.Frame(self.t_carte)
        barre_carte.pack(side="top", fill="x", padx=8, pady=(4, 0))
        ttk.Label(barre_carte, text="Véhicule affiché :").pack(side="left")
        self.var_veh_carte = tk.StringVar(value="Tous")
        self.cb_veh_carte = ttk.Combobox(barre_carte, textvariable=self.var_veh_carte,
                                         state="readonly", width=12, values=["Tous"])
        self.cb_veh_carte.pack(side="left", padx=4)
        self.cb_veh_carte.bind("<<ComboboxSelected>>", self._redessiner_carte)
        self.fig_c, self.cv_c = self._canevas(self.t_carte, barre_outils=True)
        self._init_energie()
        self._init_comparaison()
        self._vider_resultats("Aucun calcul pour l'instant.\nChoisir une instance, un modèle et une méthode, puis « Lancer le calcul ».")

    def _canevas(self, parent, barre_outils=False):
        fig = Figure(figsize=(7, 4.5), dpi=100)
        cv = FigureCanvasTkAgg(fig, master=parent)
        if barre_outils:
            bo = NavigationToolbar2Tk(cv, parent, pack_toolbar=False)
            bo.update()
            bo.pack(side="bottom", fill="x")
        cv.get_tk_widget().pack(fill="both", expand=True)
        return fig, cv

    # ---- Résumé
    def _init_resume(self):
        self.lbl_statut = ttk.Label(self.t_resume, text="", style="Statut.TLabel")
        self.lbl_statut.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self.champs_resume = {}
        for i, nom in enumerate(["Coût total (temps de trajet, s)", "Véhicules engagés (K)", "Temps de calcul",
                                 "Méthode", "Modèle", "Instance", "Transferts au crossdock"], start=1):
            ttk.Label(self.t_resume, text=nom + " :", foreground="#667085").grid(row=i, column=0, sticky="ne", padx=(0, 10), pady=3)
            v = ttk.Label(self.t_resume, text="—", wraplength=620, justify="left")
            v.grid(row=i, column=1, sticky="w", pady=3)
            self.champs_resume[nom] = v
        self.lbl_message = ttk.Label(self.t_resume, text="", wraplength=700, justify="left", foreground="#b42318")
        self.lbl_message.grid(row=9, column=0, columnspan=2, sticky="w", pady=(14, 0))

    # ---- Tournées
    def _init_tournees(self):
        ttk.Label(self.t_tournees, foreground="#344054", wraplength=820, justify="left",
                  text="Orange ⇄ : demande collectée par un véhicule et livrée par un autre (transfert au crossdock). "
                       "Entre parenthèses : début de service (s).").pack(anchor="w", pady=(0, 4))
        cadre = ttk.Frame(self.t_tournees)
        cadre.pack(fill="both", expand=True)
        self.txt = tk.Text(cadre, wrap="word", height=14, font=("Consolas" if sys.platform == "win32" else "DejaVu Sans Mono", 10),
                           relief="flat", background="#fbfbfc", padx=8, pady=6)
        sb = ttk.Scrollbar(cadre, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_configure("titre", font=("TkDefaultFont", 10, "bold"), spacing1=8)
        self.txt.tag_configure("transfert", foreground=COULEUR_TRANSFERT, font=("TkDefaultFont", 10, "bold"))
        self.txt.tag_configure("gris", foreground="#667085")
        for k in range(1, 61):
            self.txt.tag_configure(f"veh{k}", foreground=couleur(k), font=("TkDefaultFont", 10, "bold"), spacing1=8)

        ttk.Label(self.t_tournees, text="Transferts au crossdock", style="Titre.TLabel").pack(anchor="w", pady=(8, 2))
        self.tv_transf = ttk.Treeview(self.t_tournees, columns=("req", "coll", "livr"), show="headings", height=4)
        for c, t in [("req", "Demande"), ("coll", "Collectée par le véhicule"), ("livr", "Livrée par le véhicule")]:
            self.tv_transf.heading(c, text=t)
            self.tv_transf.column(c, width=170, anchor="center")
        self.tv_transf.tag_configure("t", foreground=COULEUR_TRANSFERT)
        self.tv_transf.pack(fill="x")

    # ---- Énergie
    def _init_energie(self):
        self.lbl_energie = ttk.Label(self.t_energie, text="", foreground="#667085")
        self.fig_e, self.cv_e = self._canevas(self.t_energie)
        self.tv_energie = ttk.Treeview(self.t_energie, show="headings", height=6,
                                       columns=("k", "ec", "el", "sa", "sb", "cdt"))
        for c, t, w in [("k", "Véhicule", 80), ("ec", "Énergie collecte (kWh)", 150), ("el", "Énergie livraison (kWh)", 150),
                        ("sa", "SoC arrivée (kWh)", 130), ("sb", "SoC départ (kWh)", 130), ("cdt", "Arrêt crossdock (s)", 130)]:
            self.tv_energie.heading(c, text=t)
            self.tv_energie.column(c, width=w, anchor="center")
        self.tv_energie.pack(side="bottom", fill="x", pady=(6, 0))

    # ---- Comparaison
    def _init_comparaison(self):
        self.lbl_compar_info = ttk.Label(self.t_compar, text="", wraplength=700, justify="left")
        self.lbl_compar_info.pack(anchor="w", pady=(0, 8))
        self.tv_compar = ttk.Treeview(self.t_compar, show="headings", height=8, columns=("critere", "alns", "exact"))
        for c, t, w in [("critere", "Critère", 220), ("alns", "ALNS", 220), ("exact", "Exact (SCIP)", 220)]:
            self.tv_compar.heading(c, text=t)
            self.tv_compar.column(c, width=w, anchor="w" if c == "critere" else "center")
        self.tv_compar.pack(fill="x")
        self.lbl_ecart = ttk.Label(self.t_compar, text="", style="Titre.TLabel")
        self.lbl_ecart.pack(anchor="w", pady=(12, 0))

    # ------------------------------------------------------------------ états des champs
    def _maj_etats(self):
        mode = self.mode_instance.get()
        for w in (self.sp_n, self.en_graine_inst, self.bt_generer):
            w.configure(state="normal" if mode == "generer" else "disabled")
        self.bt_parcourir.configure(state="normal" if mode == "fichier" else "disabled")
        for w in self.champs_ve:
            w.configure(state="normal" if self.var_ev.get() else "disabled")
        meth = self.var_methode.get()
        for w in (self.en_iter, self.en_graine):
            w.configure(state="normal" if meth in ("alns", "comparer") else "disabled")
        self.en_limite.configure(state="normal" if meth in ("exact", "comparer") else "disabled")
        self.sp_k.configure(state="disabled" if self.var_k_auto.get() else "normal")

    # ------------------------------------------------------------------ instance
    def _poser_instance(self, data):
        self.data = data
        coords = "oui" if data.get("coords") else "non (schéma à partir des distances)"
        self.lbl_instance.configure(
            text=f"{data.get('nom', 'Instance')}\n{data['n']} demandes · capacité {data['Q']} · durée de route {data['T']} s · "
                 f"ride time max {data['L']} s\nCoordonnées : {coords}")
        k_sug = data.get("K_suggere")
        if k_sug:
            self.var_k.set(str(k_sug))

    def _charger_article(self):
        self.mode_instance.set("article")
        self._poser_instance(api.instance_exemple_article())
        self._maj_etats()

    def _generer(self):
        try:
            n = int(self.var_n.get())
            graine = int(self.var_graine_inst.get())
            if not 1 <= n <= N_MAX_GENERATION:
                raise ValueError
        except ValueError:
            messagebox.showerror("Valeur non valide", f"n doit être un entier entre 1 et {N_MAX_GENERATION}, la graine un entier.")
            return
        self._poser_instance(api.generer_instance(n, graine))

    def _parcourir(self):
        exemples = os.path.join(dossier_programme(), "exemples_instances")
        chemin = filedialog.askopenfilename(title="Charger une instance", filetypes=[("Instance JSON", "*.json")],
                                            initialdir=exemples if os.path.isdir(exemples) else dossier_programme())
        if not chemin:
            return
        try:
            self._poser_instance(api.charger_instance(chemin))
        except Exception as exc:  # fichier illisible ou au mauvais format
            messagebox.showerror("Fichier non lisible", f"Impossible de charger cette instance.\n\n{exc}")

    def _enregistrer_instance(self):
        chemin = filedialog.asksaveasfilename(title="Enregistrer l'instance", defaultextension=".json",
                                              filetypes=[("Instance JSON", "*.json")])
        if chemin:
            try:
                api.sauvegarder_instance(self.data, chemin)
            except Exception as exc:
                messagebox.showerror("Échec de l'enregistrement", str(exc))

    # ------------------------------------------------------------------ lecture des paramètres
    def _lire_parametres(self):
        """Valide les champs ; renvoie un dict ou None (après un message d'erreur)."""
        def entier(var, nom, mini, maxi=None):
            try:
                v = int(var.get())
            except ValueError:
                raise ValueError(f"{nom} doit être un entier.")
            if v < mini or (maxi is not None and v > maxi):
                raise ValueError(f"{nom} doit être ≥ {mini}" + (f" et ≤ {maxi}." if maxi else "."))
            return v

        def reel(var, nom):
            try:
                v = float(var.get().replace(",", "."))
            except ValueError:
                raise ValueError(f"{nom} doit être un nombre.")
            if v <= 0:
                raise ValueError(f"{nom} doit être strictement positif.")
            return v

        try:
            meth = self.var_methode.get()
            ev = self.var_ev.get()
            p = {"methode": meth, "ev": ev, "params_ve": None, "K": None, "iterations": 300, "graine": 1, "limite": 60}
            if ev:
                p["params_ve"] = {"e_rate": reel(self.var_e, "La consommation"), "soc_max": reel(self.var_soc, "La batterie maximale"),
                                  "v_charge": reel(self.var_v, "La puissance de recharge")}
            if not self.var_k_auto.get():
                p["K"] = entier(self.var_k, "K", 1, self.data["n"])
            if meth in ("alns", "comparer"):
                p["iterations"] = entier(self.var_iter, "Le nombre d'itérations", 1, 100000)
                p["graine"] = entier(self.var_graine, "La graine", 0)
            if meth in ("exact", "comparer"):
                p["limite"] = entier(self.var_limite, "La limite de temps", 1, 3600)
            return p
        except ValueError as exc:
            messagebox.showerror("Valeur non valide", str(exc))
            return None

    # ------------------------------------------------------------------ calcul (fil séparé)
    def lancer(self):
        if self.en_cours or self.data is None:
            return
        p = self._lire_parametres()
        if p is None:
            return
        if p["methode"] in ("exact", "comparer") and self.data["n"] > N_EXACT_AVERTISSEMENT:
            if not messagebox.askokcancel(
                    "Solveur exact : instance volumineuse",
                    f"Avec {self.data['n']} demandes, le solveur exact ne trouve en général plus de solution "
                    f"dans la limite de temps (limite actuelle : {p['limite']} s).\n\n"
                    "L'ALNS reste utilisable à cette taille. Lancer quand même ?"):
                return
        self.annuler.clear()
        self.file = queue.Queue()
        self._etat_calcul(True)
        data = self.data
        threading.Thread(target=self._travail, args=(data, p), daemon=True).start()
        self.after(100, self._lire_file)

    def _travail(self, data, p):
        """Exécuté dans le fil de calcul : n'appelle QUE api_interface, ne touche à aucun widget."""
        q = self.file
        try:
            K = p["K"]
            if K is None:
                q.put(("phase", "Recherche de la taille de flotte…", None))
                K = api.trouver_k_minimal(data, p["ev"], p["params_ve"])
                if K is None:
                    q.put(("done", {"data": data, "p": p, "res": {}, "echec": "Aucune flotte trouvée pour construire une solution."}))
                    return
            resultats = {}
            if p["methode"] in ("alns", "comparer"):
                q.put(("phase", f"ALNS : K = {K}", 0))

                def progress(it, total, meilleur):          # appelée à chaque itération par l'ALNS
                    if it % 3 == 0 or it >= total - 1:
                        q.put(("progress", it, total, meilleur))
                    return self.annuler.is_set()            # True -> l'ALNS s'arrête

                resultats["alns"] = api.resoudre(data, "alns", K=K, ev=p["ev"], params_ve=p["params_ve"],
                                                 iterations=p["iterations"], graine=p["graine"], progress=progress)
            if p["methode"] in ("exact", "comparer") and not self.annuler.is_set():
                q.put(("phase", f"Solveur exact : K = {K}, limite {p['limite']} s (pas d'annulation possible)", None))
                resultats["exact"] = api.resoudre(data, "exact", K=K, ev=p["ev"], params_ve=p["params_ve"],
                                                  limite_temps_s=p["limite"])
            q.put(("done", {"data": data, "p": p, "K": K, "res": resultats, "annule": self.annuler.is_set()}))
        except Exception:
            q.put(("erreur", traceback.format_exc()))

    def _lire_file(self):
        """Exécuté dans le fil de l'interface : vide la file des messages du calcul."""
        try:
            while True:
                msg = self.file.get_nowait()
                kind = msg[0]
                if kind == "phase":
                    self.var_etat.set(msg[1])
                    if msg[2] is None:                       # phase non interruptible : K auto ou solveur exact
                        self.barre.configure(mode="indeterminate")
                        self.barre.start(15)
                        self.bt_annuler.configure(state="disabled")
                    else:                                    # ALNS : progression connue, annulation possible
                        self.barre.stop()
                        self.barre.configure(mode="determinate", value=0)
                        self.bt_annuler.configure(state="normal")
                elif kind == "progress":
                    _, it, total, meilleur = msg
                    self.barre.configure(value=100.0 * (it + 1) / total)
                    self.var_etat.set(f"ALNS : itération {it + 1}/{total} · meilleur coût {fmt(meilleur)}")
                elif kind == "done":
                    self._etat_calcul(False)
                    self._calcul_termine(msg[1])
                    return
                elif kind == "erreur":
                    self._etat_calcul(False)
                    messagebox.showerror("Erreur pendant le calcul", msg[1][-1500:])
                    return
        except queue.Empty:
            pass
        if self.en_cours:
            self.after(100, self._lire_file)

    def demander_annulation(self):
        self.annuler.set()
        self.var_etat.set("Annulation demandée…")
        self.bt_annuler.configure(state="disabled")

    def _etat_calcul(self, actif):
        self.en_cours = actif
        self.bt_lancer.configure(state="disabled" if actif else "normal")
        self.bt_annuler.configure(state="disabled")
        if actif:
            self.barre.stop()
            self.barre.configure(mode="determinate", value=0)
            self.var_etat.set("Calcul en cours…")
        else:
            self.barre.stop()
            self.barre.configure(mode="determinate")

    # ------------------------------------------------------------------ affichage des résultats
    def _calcul_termine(self, payload):
        if payload.get("echec"):
            self.var_etat.set("Aucune solution.")
            self._vider_resultats(payload["echec"])
            messagebox.showwarning("Aucune solution", payload["echec"])
            return
        self.payload = payload
        res = payload["res"]
        self.barre.configure(value=100)
        if payload["p"]["methode"] == "comparer" and "exact" in res:
            self.cb_choix.configure(values=["ALNS", "Exact"])
            self.var_choix.set("ALNS")
            self._montrer_choix(True)
            self.res_affiche = res["alns"]
        else:
            cle = "alns" if "alns" in res else "exact"
            self._montrer_choix(False)
            self.res_affiche = res[cle]
        suffixe = " (interrompu par l'utilisateur)" if payload.get("annule") else ""
        self.var_etat.set("Terminé" + suffixe + ".")
        self._rafraichir()
        self.onglets.select(self.t_resume)

    def _montrer_choix(self, visible):
        """Le sélecteur « Résultat affiché » n'apparaît qu'en mode comparaison."""
        if visible:
            self.lbl_choix.pack(side="left", padx=(20, 4))
            self.cb_choix.pack(side="left")
        else:
            self.lbl_choix.pack_forget()
            self.cb_choix.pack_forget()

    def _changer_affichage(self, _evt=None):
        cle = "alns" if self.var_choix.get() == "ALNS" else "exact"
        self.res_affiche = self.payload["res"][cle]
        self._rafraichir()

    def _rafraichir(self):
        res, payload = self.res_affiche, self.payload
        data = payload["data"]
        ev = payload["p"]["ev"]
        self._maj_resume(res, payload)
        sans_solution = res.get("solution") is None
        if sans_solution:
            msg = res.get("message") or "Pas de solution à afficher."
            self._maj_texte_tournees(None, None)
            self._dessiner_vide(self.fig_h, self.cv_h, msg)
            self._dessiner_vide(self.fig_c, self.cv_c, msg)
        else:
            self._maj_texte_tournees(res, data)
            self._dessiner_horaires(res, data)
            self._dessiner_carte(res, data)
        self._maj_energie(res, payload, ev, sans_solution)
        self._maj_comparaison(payload)
        compar = payload["p"]["methode"] == "comparer" and "exact" in payload["res"]
        self.onglets.tab(self.t_compar, state="normal" if compar else "disabled")
        self.onglets.tab(self.t_energie, state="normal" if ev else "disabled")
        peut_exporter = not sans_solution or compar
        self.bt_json.configure(state="normal" if peut_exporter else "disabled")
        self.bt_csv.configure(state="normal" if not sans_solution else "disabled")

    def _vider_resultats(self, message):
        self.payload = None
        self.res_affiche = None
        self._montrer_choix(False)
        for fig, cv in ((self.fig_h, self.cv_h), (self.fig_c, self.cv_c), (self.fig_e, self.cv_e)):
            self._dessiner_vide(fig, cv, message)
        self.lbl_statut.configure(text=" Aucun résultat ", background="#667085")
        for v in self.champs_resume.values():
            v.configure(text="—")
        self.lbl_message.configure(text=message, foreground="#344054")
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")
        self.tv_transf.delete(*self.tv_transf.get_children())
        self.tv_energie.delete(*self.tv_energie.get_children())
        self.tv_compar.delete(*self.tv_compar.get_children())
        self.lbl_ecart.configure(text="")
        self.lbl_compar_info.configure(text="")
        self.onglets.tab(self.t_compar, state="disabled")
        self.onglets.tab(self.t_energie, state="disabled")
        self.bt_json.configure(state="disabled")
        self.bt_csv.configure(state="disabled")
        self.var_veh_carte.set("Tous")
        self.cb_veh_carte.configure(values=["Tous"])

    @staticmethod
    def _dessiner_vide(fig, cv, message):
        fig.clear()
        fig.text(0.5, 0.5, message, ha="center", va="center", color="#667085", fontsize=11, wrap=True)
        cv.draw_idle()

    # ---- Résumé
    def _maj_resume(self, res, payload):
        p = payload["p"]
        statut = res["statut"]
        self.lbl_statut.configure(text=" " + libelle_statut(res) + " ", background=COULEURS_STATUT[statut])
        c = self.champs_resume
        c["Coût total (temps de trajet, s)"].configure(text=fmt(res.get("cout")))
        k_txt = str(res.get("K", "—"))
        if res.get("k_auto") or p["K"] is None:
            k_txt += " (choisi automatiquement)"
        c["Véhicules engagés (K)"].configure(text=k_txt)
        c["Temps de calcul"].configure(text=fmt(res.get("temps_s"), 1, " s"))
        c["Méthode"].configure(text="ALNS (%d itérations, graine %d)" % (p["iterations"], p["graine"])
                               if res["methode"] == "alns" else "Solveur exact SCIP (limite %d s)" % p["limite"])
        if p["ev"]:
            pv = {**api.PARAMS_VE_DEFAUT, **(p["params_ve"] or {})}
            c["Modèle"].configure(text="Véhicules électriques (e = %s kWh/km, batterie %s kWh, recharge %s kW)"
                                  % (fmt(pv["e_rate"], 2), fmt(pv["soc_max"], 0), fmt(pv["v_charge"], 0)))
        else:
            c["Modèle"].configure(text="Véhicules conventionnels")
        c["Instance"].configure(text=payload["data"].get("nom", "—"))
        nt = len(res.get("transferts") or [])
        c["Transferts au crossdock"].configure(text="aucun" if res.get("solution") and nt == 0 else str(nt) if nt else "—")
        msg = res.get("message", "")
        if payload.get("annule") and res["methode"] == "alns" and res.get("solution") is not None:
            msg = (msg + "\n" if msg else "") + "Calcul interrompu par l'utilisateur : meilleure solution trouvée jusque-là."
        if res["statut"] == "infaisable" and not msg:
            msg = "Aucune solution trouvée."
        self.lbl_message.configure(text=msg, foreground=COULEURS_STATUT["infaisable"] if res["statut"] == "infaisable" else "#8a5a00")

    # ---- Tournées
    def _maj_texte_tournees(self, res, data):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.tv_transf.delete(*self.tv_transf.get_children())
        if res is None:
            self.txt.insert("end", "Pas de solution à afficher.", "gris")
            self.txt.configure(state="disabled")
            return
        transf = {t["requete"] for t in res["transferts"]}
        for v in res["details"]:
            k = v["k"]
            self.txt.insert("end", f"Véhicule {k}\n", f"veh{k}")
            self.txt.insert("end", "  Collecte   : ")
            self._ecrire_arrets(v["collecte"], transf)
            self.txt.insert("end", f"\n             distance {fmt(v['distance_collecte'], 1)}\n", "gris")
            self.txt.insert("end", f"  Crossdock  : arrivée {fmt(v['u_o2'], 1)} s · départ {fmt(v['u_o3'], 1)} s\n")
            self.txt.insert("end", "  Livraison  : ")
            self._ecrire_arrets(v["livraison"], transf)
            self.txt.insert("end", f"\n             distance {fmt(v['distance_livraison'], 1)} · retour au crossdock {fmt(v['u_o4'], 1)} s\n", "gris")
        self.txt.configure(state="disabled")
        if res["transferts"]:
            for t in res["transferts"]:
                self.tv_transf.insert("", "end", values=(t["requete"], t["collecte_par"], t["livree_par"]), tags=("t",))
        else:
            self.tv_transf.insert("", "end", values=("aucun transfert", "", ""))

    def _ecrire_arrets(self, arrets, transf):
        for i, a in enumerate(arrets):
            if i:
                self.txt.insert("end", "  →  ")
            r = a["requete"]
            txt = f"{r}" + (" ⇄" if r in transf else "")
            self.txt.insert("end", txt, "transfert" if r in transf else "")
            self.txt.insert("end", f" ({fmt(a['debut_service'], 0)})", "gris")

    # ---- Horaires : un diagramme par véhicule
    def _dessiner_horaires(self, res, data):
        fig = self.fig_h
        fig.clear()
        det = res["details"]
        transf = {t["requete"] for t in res["transferts"]}
        ax = fig.add_subplot(111)
        ax.set_ylim(len(det) + 0.4, 0.2)
        h = 0.55
        for v in det:
            y = v["k"]
            ax.barh(y, v["u_o2"] - v["u_o1"], left=v["u_o1"], height=h, color="#a5c8e8", edgecolor="#3b6ea5")
            ax.barh(y, v["u_o3"] - v["u_o2"], left=v["u_o2"], height=h, color="#d0d5dd", edgecolor="#667085", hatch="//")
            ax.barh(y, v["u_o4"] - v["u_o3"], left=v["u_o3"], height=h, color="#a9dcc4", edgecolor="#1b7f5c")
            for phase, marque in (("collecte", "^"), ("livraison", "s")):
                for a in v[phase]:
                    r = a["requete"]
                    col = COULEUR_TRANSFERT if r in transf else "#101828"
                    ax.plot(a["debut_service"], y, marque, color=col, markersize=5)
                    ax.annotate(str(r), (a["debut_service"], y - h / 2 - 0.02), ha="center", va="bottom", fontsize=8, color=col,
                                fontweight="bold" if r in transf else "normal")
        ax.set_yticks([v["k"] for v in det])
        ax.set_yticklabels([f"Véhicule {v['k']}" for v in det], fontsize=9 if len(det) <= 10 else 7)
        ax.set_xlabel("Temps (s)")
        ax.grid(axis="x", alpha=0.3)
        ax.set_title("Horaires : collecte, arrêt au crossdock, livraison", fontsize=11)
        ax.legend(handles=[Patch(facecolor="#a5c8e8", edgecolor="#3b6ea5", label="trajet de collecte"),
                           Patch(facecolor="#d0d5dd", edgecolor="#667085", hatch="//", label="arrêt au crossdock"),
                           Patch(facecolor="#a9dcc4", edgecolor="#1b7f5c", label="trajet de livraison"),
                           Line2D([], [], marker="^", color="#101828", ls="", label="collecte (n° de demande)"),
                           Line2D([], [], marker="s", color="#101828", ls="", label="livraison (n° de demande)"),
                           Line2D([], [], marker="o", color=COULEUR_TRANSFERT, ls="", label="demande transférée")],
                  loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=3, fontsize=8, frameon=False)
        fig.subplots_adjust(left=0.1, right=0.97, top=0.92, bottom=0.25)
        self.cv_h.draw_idle()

    def _redessiner_carte(self, _evt=None):
        if self.res_affiche and self.payload and self.res_affiche.get("solution") is not None:
            self._dessiner_carte(self.res_affiche, self.payload["data"])

    # ---- Carte
    def _dessiner_carte(self, res, data):
        fig = self.fig_c
        fig.clear()
        schema = False
        coords = data.get("coords")
        if not coords:
            if not data.get("t") or not data.get("t_cd"):
                fig.text(0.5, 0.5, "Pas de coordonnées pour ce réseau (réseau de l'article : distances seulement).\n"
                                   "Voir les onglets Tournées et Horaires.", ha="center", va="center", color="#667085", fontsize=11)
                self.cv_c.draw_idle()
                return
            coords = positions_schema(data)
            schema = True
        n = data["n"]
        vehicules = ["Tous"] + [f"Véhicule {v['k']}" for v in res["details"]]
        actuel = self.var_veh_carte.get()
        self.cb_veh_carte.configure(values=vehicules)
        if actuel not in vehicules:
            self.var_veh_carte.set("Tous")
            actuel = "Tous"
        ax = fig.add_subplot(111)
        for k, phase, labels in api.chemins(data, res["solution"]):
            if actuel != "Tous" and actuel != f"Véhicule {k}":
                continue
            pts = [coords[l] for l in labels]
            for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
                ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                            arrowprops=dict(arrowstyle="->", color=couleur(k), lw=1.4,
                                            ls="-" if phase == "collecte" else "--", shrinkA=6, shrinkB=6))
        transf = {t["requete"] for t in res["transferts"]}
        for i in range(1, n + 1):
            x, y = coords[i]
            ax.plot(x, y, "o", color=COULEUR_TRANSFERT if i in transf else "#101828", markersize=7, zorder=3)
            ax.annotate(f"C{i}", (x, y), textcoords="offset points",
                        xytext=(7, 4 + 8 * ((i - 1) % 4 - 1)), fontsize=8)
            x, y = coords[i + n]
            ax.plot(x, y, "s", color=COULEUR_TRANSFERT if i in transf else "#101828", markersize=7, zorder=3)
            ax.annotate(f"L{i}", (x, y), textcoords="offset points",
                        xytext=(7, -10 - 6 * ((i - 1) % 3)), fontsize=8)
        ax.plot(*coords["CD"], "*", color="#b42318", markersize=17, zorder=4)
        ax.annotate("CD", coords["CD"], textcoords="offset points", xytext=(8, 8), fontsize=9,
                    color="#b42318", fontweight="bold")
        ax.set_aspect("equal", adjustable="datalim")
        ax.margins(0.14)
        ax.grid(alpha=0.25)
        ax.set_title("Carte : collecte en trait plein, livraison en pointillé", fontsize=11)
        manches = [Line2D([], [], color=couleur(v["k"]), lw=2, label=f"Véhicule {v['k']}") for v in res["details"]]
        manches += [Line2D([], [], marker="o", color="#101828", ls="", label="collecte (C1 à Cn)"),
                    Line2D([], [], marker="s", color="#101828", ls="", label="livraison (L1 à Ln)"),
                    Line2D([], [], marker="*", color="#b42318", ls="", markersize=12, label="crossdock")]
        if transf:
            manches.append(Line2D([], [], marker="o", color=COULEUR_TRANSFERT, ls="", label="demande transférée"))
        ax.legend(handles=manches, loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8, frameon=False)
        fig.subplots_adjust(left=0.06, right=0.78, top=0.92, bottom=0.12 if schema else 0.08)
        if schema:
            fig.text(0.40, 0.02, "Schéma calculé à partir des distances (positions approximatives, hors échelle)",
                     ha="center", va="bottom", color="#667085", fontsize=8)
        self.cv_c.draw_idle()

    # ---- Énergie
    def _maj_energie(self, res, payload, ev, sans_solution):
        self.tv_energie.delete(*self.tv_energie.get_children())
        fig = self.fig_e
        fig.clear()
        if not ev:
            self._dessiner_vide(fig, self.cv_e, "Onglet réservé aux véhicules électriques.")
            return
        if sans_solution:
            self._dessiner_vide(fig, self.cv_e, res.get("message") or "Pas de solution à afficher.")
            return
        pv = {**api.PARAMS_VE_DEFAUT, **(payload["p"]["params_ve"] or {})}
        det = res["details"]
        ax = fig.add_subplot(111)
        xs = list(range(len(det)))
        w = 0.36
        ax.bar([x - w / 2 for x in xs], [v["soc_a"] for v in det], w, color="#a5c8e8", edgecolor="#3b6ea5", label="à l'arrivée au crossdock")
        ax.bar([x + w / 2 for x in xs], [v["soc_b"] for v in det], w, color="#a9dcc4", edgecolor="#1b7f5c", label="au départ (après recharge)")
        ax.axhline(pv["soc_max"], color="#101828", ls="--", lw=1, label=f"batterie max ({fmt(pv['soc_max'], 0)} kWh)")
        ax.axhline(SOC_MIN_FRACTION * pv["soc_max"], color="#b42318", ls=":", lw=1.4,
                   label=f"seuil de sécurité ({fmt(SOC_MIN_FRACTION * pv['soc_max'], 0)} kWh)")
        ax.set_xticks(xs)
        ax.set_xticklabels([f"Véh. {v['k']}" for v in det], fontsize=9 if len(det) <= 10 else 7)
        ax.set_ylabel("État de charge (kWh)")
        ax.set_title("État de charge des batteries", fontsize=11)
        ax.legend(fontsize=8, loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=2, frameon=False)
        fig.subplots_adjust(left=0.09, right=0.97, top=0.92, bottom=0.30)
        self.cv_e.draw_idle()
        for v in det:
            self.tv_energie.insert("", "end", values=(v["k"], fmt(v["energie_collecte"], 1), fmt(v["energie_livraison"], 1),
                                                      fmt(v["soc_a"], 1), fmt(v["soc_b"], 1), fmt(v["cdt"], 1)))

    # ---- Comparaison
    def _maj_comparaison(self, payload):
        self.tv_compar.delete(*self.tv_compar.get_children())
        self.lbl_ecart.configure(text="")
        self.lbl_compar_info.configure(text="")
        res = payload["res"]
        if not (payload["p"]["methode"] == "comparer" and "alns" in res and "exact" in res):
            return
        a, e = res["alns"], res["exact"]
        self.lbl_compar_info.configure(
            text=f"Même instance, même flotte K = {payload['K']}. Pour l'exact, « faisable » signifie que la limite de temps "
                 "a été atteinte sans preuve d'optimalité : l'écart n'est alors pas un écart à l'optimum.")
        lignes = [("Statut", libelle_statut(a), libelle_statut(e)),
                  ("Coût total", fmt(a.get("cout")), fmt(e.get("cout"))),
                  ("Véhicules (K)", str(a.get("K", "—")), str(e.get("K", "—"))),
                  ("Temps de calcul", fmt(a.get("temps_s"), 1, " s"), fmt(e.get("temps_s"), 1, " s")),
                  ("Transferts", str(len(a.get("transferts") or [])) if a.get("solution") else "—",
                   str(len(e.get("transferts") or [])) if e.get("solution") else "—")]
        for l in lignes:
            self.tv_compar.insert("", "end", values=l)
        if a.get("cout") is not None and e.get("cout") is not None and e["cout"] > 0:
            ecart = (a["cout"] - e["cout"]) / e["cout"] * 100
            sens = "ALNS plus coûteux que l'exact" if ecart > 0.005 else "ALNS meilleur que l'exact" if ecart < -0.005 else "même coût"
            self.lbl_ecart.configure(text=f"Écart (ALNS − exact) / exact : {fmt(ecart, 2, ' %')}   ({sens})")
        else:
            self.lbl_ecart.configure(text="Écart non calculable : l'une des méthodes n'a pas de solution.")

    # ------------------------------------------------------------------ export
    def _exporter(self, fmt_export):
        if self.payload is None:
            return
        ext = ".json" if fmt_export == "json" else ".csv"
        chemin = filedialog.asksaveasfilename(title="Exporter le résultat", defaultextension=ext,
                                              filetypes=[(fmt_export.upper(), "*" + ext)])
        if not chemin:
            return
        try:
            if fmt_export == "json":
                res = self.payload["res"]
                if self.payload["p"]["methode"] == "comparer" and "exact" in res:
                    a, e = res["alns"], res["exact"]
                    ecart = None
                    if a.get("cout") is not None and e.get("cout") is not None and e["cout"] > 0:
                        ecart = (a["cout"] - e["cout"]) / e["cout"] * 100
                    api.exporter_json({"K": self.payload["K"], "alns": a, "exact": e, "ecart_pct": ecart}, chemin)
                else:
                    api.exporter_json(self.res_affiche, chemin)
            else:
                api.exporter_csv(self.res_affiche, chemin)
            self.var_etat.set(f"Exporté : {os.path.basename(chemin)}")
        except Exception as exc:
            messagebox.showerror("Échec de l'export", str(exc))

    # ------------------------------------------------------------------ fermeture
    def destroy(self):
        if self.en_cours:
            if not messagebox.askyesno("Calcul en cours", "Un calcul est en cours. Quitter quand même ?"):
                return
            super().destroy()
            os._exit(0)          # le solveur exact ne peut pas être interrompu proprement
        super().destroy()


def autotest():
    """
    Vérification sans fenêtre, utile pour tester l'exécutable sur une autre machine :
        cl02 --autotest        ->  écrit cl02_autotest.txt dans le dossier courant
    Résout le réseau de l'article (ALNS puis exact, valeur attendue 1101,05) et teste le chargement d'un exemple.
    """
    lignes, ok = [], True
    try:
        data = api.instance_exemple_article()
        a = api.resoudre(data, "alns", K=2)
        e = api.resoudre(data, "exact", K=2)
        lignes.append(f"ALNS  : {a['statut']}, coût {a['cout']:.2f}, {a['temps_s']:.1f} s")
        lignes.append(f"Exact : {e['statut']}, coût {e['cout']:.2f}, {e['temps_s']:.1f} s")
        ok = abs(a["cout"] - 1101.05) < 0.02 and e["statut"] == "optimal" and abs(e["cout"] - 1101.05) < 0.02
        exemple = os.path.join(dossier_programme(), "exemples_instances", "synthetique_n8_graine42.json")
        d8 = api.charger_instance(exemple)
        lignes.append(f"Exemple chargé : {d8['n']} demandes")
        ok = ok and d8["n"] == 8
    except Exception:
        ok = False
        lignes.append(traceback.format_exc())
    lignes.append("RÉSULTAT : " + ("OK" if ok else "ÉCHEC"))
    with open("cl02_autotest.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")
    print("\n".join(lignes))
    return 0 if ok else 1


def main():
    if "--autotest" in sys.argv:
        sys.exit(autotest())
    try:                                           # netteté sous Windows (écrans à forte densité)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    Application().mainloop()


if __name__ == "__main__":
    main()
