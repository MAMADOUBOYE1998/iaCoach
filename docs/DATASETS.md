# Données annotées : ce que les bases publiques règlent, et ce qu'elles ne règlent pas

M2 et M4 sont bloqués sur des « clips annotés ». Ce terme recouvre **quatre
besoins distincts**, et les bases publiques en couvrent trois. Le quatrième est
celui qui différencie ce projet d'un template — d'où l'intérêt de ne pas les
confondre.

---

## 1. Précision de comptage — **couvert**

Il faut des vidéos avec un nombre de répétitions vrai. C'est un problème
classique, avec une littérature et des jeux de données dédiés :

| Jeu | Ce qu'il apporte | Réserve |
|---|---|---|
| **RepCount / RepCountA** (TransRAC, CVPR 2022) | Comptage en conditions réelles, annotations début/fin par répétition, plusieurs exercices dont tractions | Vidéos tierces, cadrages variés |
| **Countix** (RepNet, CVPR 2020) | Comptage à l'échelle du clip, large | Liens YouTube : téléchargement à faire, disponibilité qui se dégrade |
| **QUVA Repetition** | 100 vidéos comptées, très propre | Petit, mouvements génériques |
| **UCF101**, **Kinetics** | Contiennent `pull ups`, `push ups` | Étiquettes d'action seulement : **aucun comptage** |

Les métriques standards sont MAE, OBO (à ±1 près) et MAPE — celles que
`vision/eval/` produit, précisément pour que nos chiffres soient comparables aux
chiffres publiés.

## 2. Classification d'exercice — **couvert**

Kinetics, UCF101 et les jeux « workout » de Kaggle donnent des clips étiquetés
par exercice. C'est exactement ce dont le classifieur de M2 a besoin.

## 3. Vérité terrain de pose pour le fine-tuning — **couvert, partiellement**

| Jeu | Ce qu'il apporte | Réserve |
|---|---|---|
| **Penn Action** | 2 326 clips, 15 actions dont `pullup`, **13 articulations annotées par frame** | 2D, résolution d'époque (2013) |
| **Fit3D** | Pose 3D issue de mocap, dizaines d'exercices, sujets multiples | Salle, pas de barre de traction en extérieur |

Utilisable pour M4 : mesurer si un modèle fine-tuné bat MediaPipe sur des
postures difficiles demande une vérité terrain de keypoints, et c'est ce que ces
deux-là fournissent.

## 4. Qualité de mouvement fine — **non couvert, et c'est le point dur**

Personne ne publie, pour des tractions : l'amplitude en degrés répétition par
répétition, le kipping, l'asymétrie gauche/droite, le tempo par phase. Le plus
proche est **Fitness-AQA** (ECCV 2022), qui annote des *défauts de forme* — mais
sur des mouvements avec charge (squat, soulevé de terre), pas sur du kipping en
traction.

Et il y a un obstacle structurel, pas seulement un manque :

> **Nos scores sont définis relativement à l'amplitude calibrée de l'athlète.**
> Un seuil ne dit pas « coude à moins de 90° », il dit « moins de 12 % de *ta*
> plage ». Une base publique n'a pas de calibration par sujet, et n'en aura
> jamais.

Le harnais contourne ça en **estimant la calibration depuis le clip lui-même**
(l'amplitude observée). C'est jouable pour du comptage, mais ça **flatte le
résultat** : on donne au compteur exactement la plage sur laquelle on va le
tester. Un chiffre issu d'une base publique est donc une **borne basse du
travail restant**, pas un substitut à une mesure sur séance réelle.

Conséquence : la qualité fine se valide sur des clips à soi, annotés à la main,
ou pas du tout. Une trentaine de séries filmées, comptées et notées suffit à
recaler `kip_tolerance_ms` et `trunk_tolerance_deg`, qui restent des
placeholders.

---

## Ce que ça change concrètement

**Le blocage n'était pas la disponibilité des données.** Il était que rien, dans
ce dépôt, ne savait transformer une vidéo en `RepEvent`. C'est fait :

- `iacoach.frame` — le `FrameSampler` porté en Python, miroir du TypeScript,
  conformance vérifiée en CI sur `fixtures/landmarks/` ;
- `vision/eval/evaluate.py` — vidéo → MediaPipe → `FrameSample` → `RepCounter`
  → MAE / OBO / MAPE ;
- `iacoach.evaluation` — la logique de métrique, testée.

Le pipeline complet est mesuré, pose comprise. Compter parfaitement à partir de
keypoints parfaits ne dit rien de ce que produit une vraie caméra.

## Téléchargement : à faire hors de cet environnement

Le proxy réseau de l'environnement de développement **bloque Kaggle et
HuggingFace** (connexion refusée) ; GitHub et PyPI passent. Les jeux ci-dessus
n'ont donc pas été téléchargés ni vérifiés depuis ici : la liste vient de la
littérature, pas d'une inspection. **Vérifier la licence de chacun au moment du
téléchargement** — plusieurs sont réservés à un usage recherche.

Une fois les clips récupérés :

```bash
cd web && npm run vendor-assets          # le .task que l'app embarque
cd .. && PYTHONPATH=backend/src python -m vision.eval.evaluate \
    fixtures/clips/manifest.json --out docs/results/counting.json
```

Format du manifeste :

```json
{"clips": [{"path": "pullup_01.mp4", "reps": 8, "exercise": "pull_up"}]}
```

`fixtures/clips/` est gitignoré : les vidéos d'entraînement sont des données
personnelles et ne remontent pas dans le dépôt.
