# vision/finetune — pipeline de fine-tuning pose (PC / RTX)

Module séparé et reproductible. **Rien ici ne tourne dans l'application** : les
poids améliorés servent uniquement l'analyse serveur de clips uploadés. Le temps
réel on-device reste MediaPipe, pour la latence.

Statut : **spécifié, pas encore implémenté** (jalon M4).

---

## Ce qu'on fine-tune, et pourquoi

Le fine-tuning utile porte sur la **vision**, pas sur un LLM. QLoRA et consorts
ne s'appliquent pas ici : c'est du transfer learning classique sur un modèle de
pose.

Le problème à résoudre est précis : les modèles de pose génériques sont entraînés
sur des poses debout, de face, non occultées. Ils décrochent sur muscle-up (corps
au-dessus de la barre, tête basse), front/back lever (corps horizontal), et sur
les occlusions barre/bras. C'est là qu'est la valeur du projet — et c'est aussi
là que le décrochage doit être *détecté* (`confidence` basse → corrections
supprimées) plutôt que subi silencieusement.

## Étapes

1. **Dataset.** Clips street workout sous angles et occlusions variés :
   tractions, dips, muscle-ups en priorité. Viser 2–3k frames annotées sur les
   postures difficiles avant d'entraîner quoi que ce soit — en dessous, le
   fine-tuning n'apportera rien de mesurable.
2. **Annotation.** Semi-automatique : passer un gros modèle (RTMPose-x ou
   YOLO11x-pose) sur les clips, puis corriger manuellement les frames où il
   décroche. Ce sont précisément les frames intéressantes.
3. **Entraînement.** Transfer learning sur YOLO11-pose et sur RTMPose, mêmes
   splits, mêmes métriques. Le choix se tranche sur le benchmark, pas a priori.
4. **Classifieur d'exercice.** Entraîné sur les mêmes clips, en sortie de
   keypoints (fenêtre glissante).
5. **Métriques avant/après** consignées dans `docs/BENCHMARKS.md`.

## Arborescence prévue

```
vision/finetune/
├── configs/       une config par run (modèle, hyperparams, splits)
├── data/          .gitignored — les clips ne quittent jamais le PC local
├── prepare.py     clips -> frames -> format COCO-pose
├── annotate.py    pré-annotation par gros modèle, export pour correction
├── train.py       entraînement, un run = une config
├── evaluate.py    métriques avant/après sur le jeu de test annoté
└── runs/          .gitignored — poids et logs
```

## Confidentialité

Les clips d'entraînement montrent une personne identifiable en train de
s'entraîner : ce sont des données personnelles sensibles. Elles restent sur le
PC local, ne sont jamais commitées (`data/` et `runs/` sont gitignorés), et ne
sont jamais envoyées à un tiers. Seuls les poids entraînés peuvent être
distribués.
