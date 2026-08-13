# Données annotées : ce que les bases publiques règlent, et ce qu'elles ne règlent pas

M2 et M4 sont bloqués sur des « clips annotés ». Ce terme recouvre **quatre
besoins distincts**, et les bases publiques en couvrent trois. Le quatrième est
celui qui différencie ce projet d'un template — d'où l'intérêt de ne pas les
confondre.

---

## 1. Précision de comptage — **couvert, mais pas comme on l'espérait**

Il faut des vidéos avec un nombre de répétitions vrai. La littérature en fournit,
mais **presque aucune ne distribue les vidéos** : elles distribuent des
annotations plus un script qui va chercher les vidéos sur YouTube. Ça marche
jusqu'au jour où la vidéo est supprimée.

| Jeu | Ce qu'il apporte | Fichiers vidéo ? |
|---|---|---|
| [**RepCount**](https://svip-lab.github.io/dataset/RepCount_dataset.html) (TransRAC, CVPR 2022) · [code](https://github.com/SvipRepetitionCounting/TransRAC) | 1 451 vidéos, ~20 000 annotations début/fin **par répétition**, tractions incluses | Part-A : à récupérer sur YouTube. **Part-B ne sera jamais publiée** ([issue 44](https://github.com/SvipRepetitionCounting/TransRAC/issues/44)) |
| [**Countix**](https://sites.google.com/view/repnet) (RepNet, CVPR 2020) | ~9 000 clips comptés, issus de Kinetics | Non : identifiants YouTube |
| [**QUVA Repetition**](http://tomrunia.github.io/projects/repetition/) | 100 vidéos, bornes de cycle + comptage total | **Oui**, [archive directe](http://isis-data.science.uva.nl/tomrunia/QUVARepetitionDataset.tar.gz) — mais mouvements génériques, peu de calisthénie |
| [**Gym Workout/Exercises Video**](https://www.kaggle.com/datasets/philosopher0808/gym-workoutexercises-video) · [variante](https://www.kaggle.com/datasets/hasyimabdillah/workoutfitness-video) (Kaggle) | Clips réels par exercice, dossier `pull Up` | **Oui**, fichiers directs (compte Kaggle requis) — mais **aucun comptage** |
| UCF101, Kinetics | Contiennent `pull ups`, `push ups` | Étiquettes d'action seulement : **aucun comptage** |

**Le chemin le plus court n'est pas le plus savant** : prendre les clips Kaggle
(fichiers réels, téléchargement direct) et **compter les répétitions à la main**
sur une vingtaine de tractions. Vingt minutes de travail, et ça donne exactement
le manifeste attendu par `vision/eval/`. RepCount est plus riche, mais son coût
d'entrée est un pipeline de téléchargement YouTube.

Les métriques standards sont MAE, OBO (à ±1 près) et MAPE — celles que
`vision/eval/` produit, précisément pour que nos chiffres soient comparables aux
chiffres publiés.

## 2. Classification d'exercice — **couvert**

Kinetics, UCF101 et les jeux « workout » de Kaggle ci-dessus donnent des clips
étiquetés par exercice. C'est exactement ce dont le classifieur de M2 a besoin,
et les mêmes fichiers servent aux deux usages.

## 3. Vérité terrain de pose pour le fine-tuning — **couvert, partiellement**

| Jeu | Ce qu'il apporte | Réserve |
|---|---|---|
| [**Penn Action**](http://dreamdragon.github.io/PennAction/) · [code](https://github.com/dreamdragon/PennAction) | 2 326 clips, 15 actions dont `pullup`, **13 articulations annotées par frame** avec visibilité et étiquette gauche/droite | 2D, résolution d'époque (2013). Distribué en **séquences d'images + `.mat`**, pas en vidéos |
| **Fit3D** | Pose 3D issue de mocap, dizaines d'exercices, sujets multiples | Salle, pas de barre de traction en extérieur |

Utilisable pour M4 : mesurer si un modèle fine-tuné bat MediaPipe sur des
postures difficiles demande une vérité terrain de keypoints, et c'est ce que ces
deux-là fournissent. **Penn Action n'a pas de comptage** — c'est de la vérité
terrain de pose, pas de répétition. Ne pas confondre les deux usages.

Note d'implémentation : `vision/eval/` lit des vidéos via OpenCV. Une séquence
d'images se lit avec un motif (`frames/%06d.jpg`), mais ça n'a pas été testé —
à vérifier au moment d'attaquer M4.

## 4. Qualité de mouvement fine — **non couvert, et c'est le point dur**

Personne ne publie, pour des tractions : l'amplitude en degrés répétition par
répétition, le kipping, l'asymétrie gauche/droite, le tempo par phase. Le plus
proche est [**Fitness-AQA**](https://github.com/ParitoshParmar/Fitness-AQA)
(ECCV 2022) : 21 284 échantillons annotés par des coachs, filmés en salle réelle
— mais sur **BackSquat, BarbellRow et OverheadPress**. Trois mouvements avec
charge, aucune traction, et des défauts qui n'ont rien à voir avec le kipping.
Accès sur demande via formulaire, usage non commercial.

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

## Où faire tourner l'évaluation

Le proxy réseau de l'environnement de développement **bloque Kaggle,
HuggingFace, et même les pages projet de RepCount et Penn Action** ; seuls
GitHub et PyPI passent. Aucun de ces jeux n'a donc été téléchargé ni inspecté
depuis ici : les liens ci-dessus sont vérifiés, leur contenu ne l'est pas.
**Vérifier la licence de chacun au téléchargement** — plusieurs sont réservés à
un usage recherche, et Fitness-AQA est explicitement non commercial.

L'évaluation tourne donc **sur la machine où sont les clips** :

```bash
git clone https://github.com/MAMADOUBOYE1998/iaCoach && cd iaCoach
cd web && npm install && npm run vendor-assets     # le .task que l'app embarque
cd ../backend && pip install -e ".[eval]"          # mediapipe + opencv
cd .. && PYTHONPATH=backend/src python -m vision.eval.evaluate \
    fixtures/clips/manifest.json --out counting.json
```

Puis coller le contenu de `counting.json` : c'est du texte, il remonte
directement dans `BENCHMARKS.md`. Les vidéos, elles, restent chez toi —
`fixtures/clips/` est gitignoré.

Format du manifeste :

```json
{"clips": [{"path": "pullup_01.mp4", "reps": 8, "exercise": "pull_up"}]}
```

`fixtures/clips/` est gitignoré : les vidéos d'entraînement sont des données
personnelles et ne remontent pas dans le dépôt.
